import { PageHeader } from "@/components/layout/PageHeader";
import { NextPhaseNotice } from "./NextPhaseNotice";

export default function AlertsPage() {
  return (
    <>
      <PageHeader
        title="Alerts"
        description="The notification inbox, split by who each alert is written for: the parts vendor or the fleet owner."
      />
      <NextPhaseNotice
        screen="Alerts"
        contents={[
          "Vendor and fleet-owner inboxes side by side",
          "Acknowledge, dismiss, or convert an alert into a work order",
          "Severity and customer filters",
          "Optimistic updates - the row changes on click, and rolls back if the write fails",
        ]}
        endpoints={[
          "GET /api/notifications",
          "PATCH /api/notifications/{id}",
          "POST /api/work-orders",
        ]}
      />
    </>
  );
}
