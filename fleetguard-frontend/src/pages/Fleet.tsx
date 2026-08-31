import { PageHeader } from "@/components/layout/PageHeader";
import { NextPhaseNotice } from "./NextPhaseNotice";

export default function FleetPage() {
  return (
    <>
      <PageHeader
        title="Fleet"
        description="Every monitored vehicle, with its worst component, failure probability, remaining life and cost exposure. The workhorse screen."
      />
      <NextPhaseNotice
        screen="Fleet"
        contents={[
          "Virtualised table over the whole result set, sorted server-side",
          "Multi-select filters: tier, customer, region, model, component",
          "Free-text search across VIN, model, region, customer and component",
          "Column visibility toggle and saved-view chips",
          "CSV export of exactly the rows on screen",
          "Row click opens the detail drawer rather than navigating away",
        ]}
        endpoints={[
          "GET /api/predictions",
          "GET /api/vehicles",
          "GET /api/export/predictions.csv",
        ]}
      />
    </>
  );
}
