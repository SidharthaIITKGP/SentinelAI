import asyncio
from engines.trust.groundedness import initialize_knowledge_base
from core.injection_detector import init_injection_detector
from core.pipeline import run_pipeline
from api.schemas import InterceptRequest

async def main():
    print('Initializing engines...')
    await initialize_knowledge_base()
    await init_injection_detector()
    print('Ready. Type exit to quit.')
    print('=' * 60)

    use_case = 'hr_copilot'

    while True:
        print()
        user_input = input('Use case (or press Enter for current: ' + use_case + '): ').strip()
        if user_input == 'exit':
            break
        if user_input in ['hr_copilot', 'customer_chatbot', 'finance_tool']:
            use_case = user_input
            print(f'Switched to: {use_case}')

        prompt = input('Prompt: ').strip()
        if prompt == 'exit':
            break
        if not prompt:
            continue

        req = InterceptRequest(
            prompt=prompt,
            use_case=use_case,
            tenant_id='acme_corp',
            user_id='demo_user'
        )
        print()
        print('Processing...')
        action, audit = await run_pipeline(req)

        print(f'ACTION:       {action.action}')
        print(f'RISK:         {audit.risk_score.overall:.3f} ({audit.risk_score.level})')
        print(f'GROUNDEDNESS: {audit.groundedness.score:.3f}')
        if audit.groundedness.flagged_claims:
            for c in audit.groundedness.flagged_claims:
                print(f'  ❌ FLAGGED: {c.claim_text[:80]}')
        print(f'LATENCY:      {audit.latency_ms}ms')
        print(f'RESPONSE:     {action.final_response}')
        print('-' * 60)

asyncio.run(main())
