import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
from soundlog_daily_record import BEGIN, END, prepare, work_section
from soundlog_memory.basic_memory_daily import sync_sources
from soundlog_memory.historical_context import search, save_search, validate_checks
from soundlog_memory.scenes import digest_bytes
from soundlog_memory.store import write_json


class DailyRecordTests(unittest.TestCase):
    def test_work_log_extracts_only_target_day_and_merges_its_fragments(self):
        log = '1125\n早一天\n\n1126\n甲\n### 2026-11-26\n乙\n1127\n晚一天'
        self.assertEqual(work_section(log, '2026-11-26'), '甲\n\n乙')

    def test_historical_review_stops_before_target_date_and_binds_references(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            notes = root / 'notes'
            day = '2030-04-15'
            events = notes / '长期记忆/事件'
            events.mkdir(parents=True)
            (events / '2030-03-09-计划.md').write_text('---\ntitle: 搬家元数据\n---\n搬家方案未确定')
            (events / (day + '-当日.md')).write_text('搬家当天')
            (events / '2030-04-16-次日.md').write_text('搬家次日')
            work = root / 'work'
            work.mkdir()
            (work / '203004.md').write_text('0414\n搬家旧记录\n0415\n搬家新记录')
            result = search(notes, work, day, ['搬家'])
            self.assertEqual({row['text'] for row in result['matches']}, {'搬家方案未确定', '搬家旧记录'})
            receipt = save_search(root, result)
            check = {'searchId': receipt['id'], 'factIds': ['current'],
                     'historicalIds': [result['matches'][0]['id']], 'outcome': 'insufficient',
                     'reason': '缺少对应地址'}
            validate_checks(root, [check], {'current': {'date': day}}, [day])
            with self.assertRaisesRegex(ValueError, '超出检索回执'):
                validate_checks(root, [{**check, 'historicalIds': ['unrelated']}],
                                {'current': {'date': day}}, [day])

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
                index = {day: {'path': str(file.relative_to(folder)), 'sha256': digest_bytes(file)}}
                self.assertEqual(sync_sources(notes, folder, index), [day])
                self.assertEqual(sync_sources(notes, folder, index), [])
                return notes / 'soundlog/sources' / (day + '.json')

            set_archive('initial', [])
            initial = prepare(notes, root / 'work', day)
            self.assertEqual(initial['dailySummary']['content'], '# 日常摘要\n\n原笔记\n')
            self.assertEqual(initial['workLog']['state'], 'missing')
            self.assertEqual(prepare(notes, root / 'work', day), initial)
            latest = set_archive('late', [{'id': 'new'}])
            updated = prepare(notes, root / 'work', day)
            self.assertEqual(updated['audio']['path'], initial['audio']['path'])
            self.assertEqual(updated['audio']['utterances'], 1)
            latest.write_text(latest.read_text().replace('new', 'tampered'))
            with self.assertRaisesRegex(ValueError, '哈希'):
                prepare(notes, root / 'work', day)
