import { PageHeader } from "@/components/layout/PageHeader";
import { NextPhaseNotice } from "./NextPhaseNotice";

export default function CommandCentrePage() {
  return (
    <>
      <PageHeader
        title="Command Centre"
        description="Where the fleet stands today: how many vehicles are monitored, what is red, what runs out of life inside a month, and what that exposure is worth."
      />
      <NextPhaseNotice
        screen="Command Centre"
        contents={[
          "A hero KPI row that counts up: vehicles monitored, red-tier components, inside 30-day RUL, total cost exposure",
          "Risk-tier donut and a 12-month failure trend line",
          "Top precursor signals across the fleet, ranked by mean weight",
          "A live \"needs attention today\" list, escalations first",
          "Cost exposure by customer",
        ]}
        endpoints={[
          "GET /api/overview",
        ]}
      />
    </>
  );
}
