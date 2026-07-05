from codex_daily_summary.summarizer import render_generation_footer, zero_cost_footer


def test_generation_footer_with_input_and_output_tokens():
    assert (
        render_generation_footer(28631, 26100, 2531)
        == "_Generation cost: 28,631 tokens (26,100 input + 2,531 output)._"
    )


def test_zero_cost_footer():
    assert zero_cost_footer() == "_Generation cost: 0 tokens (no model call)._"
