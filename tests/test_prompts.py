"""파일 조립 실패·동적 값 재해석·Worker 입력 경계를 외부 호출 없이 검증한다."""

from pathlib import Path
import re
import shutil
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from stock_agent.agents import business, macro_sector, event_catalyst, technical, sentiment
from stock_agent.agents.worker import worker_input
from stock_agent.prompts import builder
from stock_agent.state import ResearchPlan, ResearchTask


class PromptBuilderTest(unittest.TestCase):
    def test_roles_have_ordered_layers_and_common_rule_once(self):
        for role in ('orchestrator', 'request_parser', 'business', 'macro_sector', 'event_catalyst', 'technical', 'sentiment'):
            context = {'current_date': '2026-09-13'} if role in ('orchestrator', 'request_parser') else {}
            if role == 'orchestrator':
                context['execution_stage'] = 'initial'
            with self.subTest(role=role):
                prompt = builder.build_system_prompt(role, **context)
                self.assertEqual(re.findall(r'^# (\d)\. (\w+)', prompt, re.M),
                                 list(zip('123456', ['IDENTITY', 'CONSTRAINTS', 'CAPABILITIES',
                                                    'CONTEXT', 'BEHAVIOR', 'KNOWLEDGE'])))
                self.assertEqual(prompt.count('확인하지 않은 사실·수치·날짜·출처를 만들어내지 않는다.'), 1)
                self.assertNotRegex(prompt, r'\{[a-z_]+\}')

    def test_memory_is_inserted_once_without_template_interpretation(self):
        memory = '사용자는 {current_date}와 {worker_behavior}를 그대로 보여달라고 했다.'
        summary = '요약 {user_memory} {{unknown}}'
        prompt = builder.build_system_prompt('orchestrator', current_date='2026-09-13',
                                             execution_stage='initial', user_memory=memory,
                                             short_term_summary=summary)
        self.assertEqual(prompt.count(memory), 1)
        self.assertEqual(prompt.count(summary), 1)
        self.assertIn('현재 날짜: 2026-09-13', prompt)

    def test_missing_extra_and_invalid_context_fail(self):
        cases = [('orchestrator', {}), ('request_parser', {}),
                 ('../orchestrator', {}), ('business', {'user_memory': 'private'}),
                 ('request_parser', {'current_date': '2026-09-13', 'short_term_summary': 'private'}),
                 ('orchestrator', {'current_date': '2026-09-13', 'execution_stage': 'unknown'})]
        for role, context in cases:
            with self.subTest(role=role, context=context), self.assertRaises(ValueError):
                builder.build_system_prompt(role, **context)

    def test_files_are_required_and_reread_each_call(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(builder.PROMPT_DIR, root, dirs_exist_ok=True)
            with patch.object(builder, 'PROMPT_DIR', root):
                original = builder.build_system_prompt('business')
                common = root / 'common.md'
                common.write_text(common.read_text().replace('확인하지 않은 사실', '검증하지 않은 사실'))
                self.assertNotEqual(original, builder.build_system_prompt('business'))
                common.write_text('## missing\n잘못된 공통 파일\n')
                with self.assertRaises(ValueError):
                    builder.build_system_prompt('business')
                common.unlink()
                with self.assertRaises(FileNotFoundError):
                    builder.build_system_prompt('business')
                (root / 'business.md').unlink()
                with self.assertRaises(FileNotFoundError):
                    builder.build_system_prompt('business')


class WorkerPromptBoundaryTest(unittest.IsolatedAsyncioTestCase):
    async def test_each_worker_receives_own_task_and_tools_without_memory(self):
        roles = [('business', business, ['search_disclosure_evidence', 'get_financial_evidence']),
                 ('macro_sector', macro_sector, ['search_web']),
                 ('event_catalyst', event_catalyst, ['get_market_evidence', 'search_web', 'search_disclosure_evidence']),
                 ('technical', technical, ['get_technical_evidence']),
                 ('sentiment', sentiment, [])]
        plan = ResearchPlan(planning_summary='전체 계획 비공개', tasks=[
            ResearchTask(agent=role, objective=f'{role} 목표', questions=[f'{role} 질문'],
                         completion_criteria=[f'{role} 기준']) for role, _, _ in roles])
        state = {'research_plan': plan, 'research_mandate': {
            'original_question': '현재 질문 {worker_behavior}', 'research_question': '정리된 질문',
            'corp_name': '삼성전자', 'ticker': '005930', 'corp_code': '00126380',
            'as_of_date': '2026-09-01', 'period_days': 30,
            'query_start_date': '2026-08-03', 'query_end_date': '2026-09-01',
            'investment_horizon': None, 'purpose': '리서치', 'constraints': ['기준일 이후 제외']},
            'short_term_summary': '비공개 요약', 'recent_messages': [('user', '비공개 대화')],
            'memory_enabled': True, 'business_report': 'OTHER_WORKER_REPORT_PRIVATE_9f72'}
        for role, module, tools in roles:
            with self.subTest(role=role), patch.object(module, 'run_worker', new_callable=AsyncMock,
                 return_value={f'{role}_report': '근거 보고서'}) as run:
                result = await getattr(module, f'{role}_agent_node').__wrapped__(state)
                self.assertEqual(run.call_args.args[:2], (state, role))
                self.assertEqual([tool.name for tool in run.call_args.args[2]], tools)
                self.assertEqual(result, {f'{role}_report': '근거 보고서'})
                if role == 'sentiment':
                    self.assertIs(run.call_args.kwargs['collect'], sentiment.collect_sentiment_evidence)
                payload = worker_input(state, role)
                self.assertEqual(payload['mandate'], state['research_mandate'])
                task = str(payload)
                prompt = builder.build_system_prompt(role)
                for value in [f'{role} 목표', f'{role} 질문', f'{role} 기준']:
                    self.assertIn(value, task)
                for other, _, _ in roles:
                    if other != role:
                        self.assertNotIn(f'{other} 목표', task)
                for excluded in ['비공개 요약', '비공개 대화', 'OTHER_WORKER_REPORT_PRIVATE_9f72', '전체 계획 비공개']:
                    self.assertNotIn(excluded, prompt + task)
                self.assertNotIn('현재 질문', prompt)
                self.assertEqual(task.count('현재 질문 {worker_behavior}'), 1)
