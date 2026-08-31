import { PageHeader } from "@/components/layout/PageHeader";
import { NextPhaseNotice } from "./NextPhaseNotice";

export default function RulExplorerPage() {
  return (
    <>
      <PageHeader
        title="RUL Explorer"
        description="Components ranked by how much useful life is left, with overdue separated from the genuinely actionable."
      />
      <NextPhaseNotice
        screen="RUL Explorer"
        contents={[
          "Overdue grouped separately at the top - a flat list of zeros reads as a broken screen",
          "The 1-30 day band, then 31-90 days, then the rest",
          "Band counts computed across the whole scope, not the loaded page",
          "Detail pane leading with the degradation curve: observed, projected, and the failure threshold",
          "The cross-check sentence tying remaining life to failure probability",
        ]}
        endpoints={[
          "GET /api/rul",
          "GET /api/rul/bands",
          "GET /api/rul/{vin}/{part}",
        ]}
      />
    </>
  );
}
