"""Run the configured local agent CLI for one Soundlog button action."""

import json
from pathlib import Path
import re
import shutil
import subprocess

from . import product_view
from .store import write_json


AGENTS = {'codex': 'Codex', 'claude': 'Claude Code', 'hermes': 'Hermes'}
DEFAULT_SETTINGS = {'agent': 'codex', 'model': ''}


def _executable(agent):
    return shutil.which(agent) or shutil.which(str(Path.home()/'.local/bin'/agent))


def _validate_settings(data):
    if not isinstance(data, dict) or set(data) != {'agent', 'model'}:
        raise ValueError('Agent 设置格式无效')
    agent, model = data['agent'], data['model']
    if not isinstance(agent, str) or agent not in AGENTS:
        raise ValueError('请选择支持的 Agent')
    if not isinstance(model, str) or (model and not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:/@+\[\]-]{0,127}', model)):
        raise ValueError('请输入有效的模型 ID 或别名，留空则使用 Agent 默认模型')
    return {'agent': agent, 'model': model}


def settings(pipeline):
    path = pipeline.home/'agent-settings.json'
    return _validate_settings(json.loads(path.read_text())) if path.exists() else DEFAULT_SETTINGS.copy()


def settings_view(pipeline):
    return {**settings(pipeline), 'agents': [
        {'id': agent, 'label': label, 'available': bool(_executable(agent))}
        for agent, label in AGENTS.items()
    ]}


def save_settings(pipeline, data):
    selected = _validate_settings(data)
    if not _executable(selected['agent']):
        raise ValueError(f'本机找不到 {AGENTS[selected["agent"]]} 命令')
    write_json(pipeline.home/'agent-settings.json', selected)
    return selected


def pending_questions(pipeline):
    return sum(
        not (request.parent / 'answer.json').exists()
        for request in (pipeline.home / 'questions').glob('question-*/request.json')
    )


def _run_cli(pipeline, agent, args, prompt):
    executable = _executable(agent)
    label = AGENTS[agent]
    if executable is None:
        raise RuntimeError(f'找不到本机 {label} 命令')

    with (pipeline.home / 'agent-cli.log').open('ab') as log:
        result = subprocess.run(
            [executable, *args], cwd=pipeline.root, input=prompt,
            text=True, stdout=log, stderr=subprocess.STDOUT,
        )
    if result.returncode:
        raise RuntimeError(f'{label} 退出码 {result.returncode}。详见 agent-cli.log')


def run_codex(pipeline, prompt, model=''):
    args = ['-a', 'never', 'exec', '--sandbox', 'workspace-write', '--json']
    if model:
        args.extend(['--model', model])
    _run_cli(pipeline, 'codex', [*args, '-'], prompt)


def run_agent(pipeline, prompt, selected):
    agent, model = selected['agent'], selected['model']
    if agent == 'codex':
        return run_codex(pipeline, prompt, model) if model else run_codex(pipeline, prompt)
    if agent == 'claude':
        args = ['--print', '--input-format', 'text', '--permission-mode', 'acceptEdits',
                '--allowedTools', ','.join(
                    f'Bash(python3 scripts/{script}.py *)'
                    for script in ('soundlog_pipeline', 'soundlog_features', 'soundlog_library')
                )]
    elif agent == 'hermes':
        args = ['chat', '--query-file', '-', '--oneshot', '--format', 'stream-json',
                '--toolsets', 'terminal,file']
    else:
        raise ValueError('请选择支持的 Agent')
    if model:
        args.extend(['--model', model])
    _run_cli(pipeline, agent, args, prompt)


def verify_completion(pipeline, prior_state):
    with pipeline.lock():
        current = pipeline.state()
        if current['state'] != 'idle' or pipeline.inventory() or pending_questions(pipeline):
            raise RuntimeError('Agent 已退出，管线仍有待处理工作')
        published = current.get('lastBundle')
        if not published:
            return current
        catalog = product_view.delivery_days(pipeline.delivery)
        previous_days = prior_state.get('deliveryDays')
        expected = {date: bundle for date, bundle in catalog.items()
                    if previous_days is not None and previous_days.get(date) != bundle}
        previous_bundle = prior_state.get('lastBundle')
        if published != previous_bundle or prior_state['state'] == 'awaiting_enrichment':
            receipt = json.loads((pipeline.delivery/published/'receipt.json').read_text())
            if receipt['state'] != 'completed' or receipt['bundle'] != published or not receipt['days']:
                raise ValueError('本批日交付回执无效')
            for date in receipt['days']:
                if catalog.get(date) != published:
                    raise ValueError(f'{date} 的目录未指向本批交付包')
                expected[date] = published
        if prior_state['state'] == 'awaiting_enrichment':
            for date, bundle in (previous_days or {}).items():
                if bundle == previous_bundle:
                    if date not in catalog:
                        raise ValueError(f'{date} 的交付已从目录缺失')
                    expected[date] = catalog[date]
        # Verify existing bindings before carrying old activities forward.
        product_view.results(pipeline)
        missing = product_view.missing_delivery_days(pipeline, expected)
        if missing:
            product_view.publish_reviewed_scenes(pipeline, missing)
            product_view.results(pipeline)
            missing = product_view.missing_delivery_days(pipeline, expected)
            if missing:
                raise RuntimeError('成果页未覆盖本批日期：' + '、'.join(sorted(missing)))
        return current
