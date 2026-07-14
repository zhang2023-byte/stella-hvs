import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { ScorecardView } from "./EvaluatePage";

afterEach(cleanup);

describe("ScorecardView", () => {
  it("展示分层指标、区间与逐论文 TP/FP/FN，但不生成总分", () => {
    render(<ScorecardView card={{ run_label: "run-b", run_source: { model: "model-b" }, l1: { micro: { precision: .5, recall: .75, f1: .6 }, bootstrap: { micro_f1_ci95: [.4, .8], micro_precision_ci95: [.3, .7], micro_recall_ci95: [.6, .9] }, per_paper: [{ arxiv_id: "1804.10179", tp: 2, fp: 1, fn: 3, f1: .5 }] }, l2: { micro: { agreement_over_compared_strict: .8, delivery_end_to_end_strict: .6, fill_precision_strict: .7, coverage: .9, ai_only: 4 }, bootstrap: { agreement_over_compared_strict_ci95: [.7, .9], delivery_end_to_end_strict_ci95: [.4, .8], fill_precision_strict_ci95: [.5, .9] } } }} />);
    expect(screen.getAllByText("60.0%")).toHaveLength(2);
    expect(screen.getByText("95% CI 30.0%–70.0%")).toBeInTheDocument();
    expect(screen.getAllByText("95% CI 40.0%–80.0%")).toHaveLength(2);
    expect(screen.getByText("2 / 1 / 3")).toBeInTheDocument();
    expect(screen.getByText(/不生成合成总分/)).toBeInTheDocument();
  });
});
