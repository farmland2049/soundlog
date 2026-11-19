"""Run the installed Codex CLI for one Soundlog button action."""

import json
from pathlib import Path
import shutil
import subprocess

from . import product_view


def pending_questions(pipeline):
    return sum(
        not (request.parent / 'answer.json').exists()
        for request in (pipeline.home / 'questions').glob('question-*/request.json')
    )


def run_codex(pipeline, prompt):
    candidates = [shutil.which('codex'), Path.home() / '.local/bin/codex']
    executable = next((path for item in candidates if item and (path := shutil.which(str(item)))), None)
    if executable is None:
        raise RuntimeError('找不到本机 Codex CLI')

    with (pipeline.home / 'agent-cli.log').open('ab') as log:
        result = subprocess.run(
            [executable, '-a', 'never', 'exec', '--sandbox', 'workspace-write', '--json', '-'],
            cwd=pipeline.root, input=prompt, text=True, stdout=log, stderr=subprocess.STDOUT,
        )
    if result.returncode:
        raise RuntimeError(f'Codex CLI 退出码 {result.returncode}。详见 agent-cli.log')


def product_version(pipeline):
    pointer = pipeline.delivery / 'product-views/latest.json'
    return json.loads(pointer.read_text())['id'] if pointer.exists() else None


def verify_completion(pipeline, prior_state, prior_product):
    with pipeline.lock():
        current = pipeline.state()
        if current['state'] != 'idle' or pipeline.inventory() or pending_questions(pipeline):
            raise RuntimeError('Agent 已退出，管线仍有待处理工作')
        published = current.get('lastBundle')
        if not published:
            return current
        # Verify existing bindings before carrying old activities forward.
        product_view.results(pipeline)
        needs_new_view = published != prior_state.get('lastBundle') or prior_state['state'] == 'awaiting_enrichment'
        if needs_new_view and product_version(pipeline) in {None, prior_product}:
            recovered = product_view.publish_reviewed_scenes(pipeline, published)
            if not recovered or recovered['id'] == prior_product:
                raise RuntimeError('成果页缺少本轮发布回执，且没有可自动补发的当日场景')
            product_view.results(pipeline)
        return current
