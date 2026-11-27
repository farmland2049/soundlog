import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
from soundlog_daily_record import BEGIN, END, prepare, work_section
from soundlog_memory.scenes import digest_bytes
from soundlog_memory.store import write_json


class DailyRecordTests(unittest.TestCase):
    def test_work_log_extracts_only_target_day_and_merges_its_fragments(self):
        log = '1125\n早一天\n\n1126\n甲\n### 2026-11-26\n乙\n1127\n晚一天'
        self.assertEqual(work_section(log, '2026-11-26'), '甲\n\n乙')

    def test_prepare_skips_prior_report_and_updates_index_for_late_archive(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            day = '2026-11-26'
            folder = root / '产出/每日录音归档'
            notes = root / 'notes'
            diary = notes / '日常摘要' / (day + '.md')
            diary.parent.mkdir(parents=True)
            diary.write_text(f'# 日常摘要\n\n原笔记\n\n## 综合记录\n\n{BEGIN}\n旧综合\n{END}\n',
                             encoding='utf-8')

            def set_archive(version, rows):
                file = folder / day / (version + '.json')
                write_json(file, {'date': day, 'sources': {}, 'utterances': rows, 'acoustics': []})
                write_json(folder / 'latest.json', {'days': {day: {
                    'path': str(file.relative_to(folder)), 'sha256': digest_bytes(file)}}})
                return file

            set_archive('initial', [])
            initial = prepare(root, notes, root / 'work', day)
            self.assertEqual(initial['dailySummary']['content'], '# 日常摘要\n\n原笔记\n')
            self.assertEqual(initial['workLog']['state'], 'missing')
            self.assertEqual(prepare(root, notes, root / 'work', day), initial)
            latest = set_archive('late', [{'id': 'new'}])
            updated = prepare(root, notes, root / 'work', day)
            self.assertEqual(updated['audio']['note'], initial['audio']['note'])
            self.assertIn('逐句原文 1 条', updated['audio']['indexMarkdown'])
            latest.write_text('{}')
            with self.assertRaisesRegex(ValueError, '哈希'):
                prepare(root, notes, root / 'work', day)
