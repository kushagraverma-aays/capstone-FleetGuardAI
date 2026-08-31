import { PageHeader } from "@/components/layout/PageHeader";
import { NextPhaseNotice } from "./NextPhaseNotice";

export default function RuleStudioPage() {
  return (
    <>
      <PageHeader
        title="Rule Studio"
        description="Pick a component, look at its failure history, see which signals precede its failures, and deploy the rule that scores the fleet."
      />
      <NextPhaseNotice
        screen="Rule Studio"
        contents={[
          "Step 1: component picker, grouped by category with search",
          "Step 2: fleet history - failures, preventive swaps, median life used, warranty cost",
          "Step 3: correlation bars with live toggles; weights re-normalise to 1.00 as signals are switched",
          "Step 4: the formula, its back-test precision, coverage and warning time, and deployment",
          "Deployed rule history per component, with version comparison",
        ]}
        endpoints={[
          "GET /api/parts",
          "GET /api/parts/{code}/history",
          "GET /api/parts/{code}/correlations",
          "POST /api/rules/preview",
          "POST /api/rules",
          "GET /api/rules/{code}/history",
        ]}
      />
    </>
  );
}
