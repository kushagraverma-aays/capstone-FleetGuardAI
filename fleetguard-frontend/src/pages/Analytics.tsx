import { PageHeader } from "@/components/layout/PageHeader";
import { NextPhaseNotice } from "./NextPhaseNotice";

export default function AnalyticsPage() {
  return (
    <>
      <PageHeader
        title="Analytics"
        description="Where the money is going, which components are failing, and how each customer compares to the fleet."
      />
      <NextPhaseNotice
        screen="Analytics"
        contents={[
          "Cost exposure by customer, component and region, with the avoidable share called out",
          "Failure trends by component over twelve months",
          "Customer benchmarking against the fleet mean",
          "Signal prevalence across the fleet",
        ]}
        endpoints={[
          "GET /api/analytics/cost-exposure",
          "GET /api/analytics/failure-trends",
          "GET /api/analytics/fleet-comparison",
        ]}
      />
    </>
  );
}
