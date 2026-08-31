import { useParams } from "react-router-dom";

import { PageHeader } from "@/components/layout/PageHeader";
import { NextPhaseNotice } from "./NextPhaseNotice";

export default function VehicleDetailPage() {
  const { vin } = useParams<{ vin: string }>();

  return (
    <>
      <PageHeader
        title={vin ?? "Vehicle"}
        description="Component health, probability trend, degradation curve and service history for one vehicle."
        showScope={false}
      />
      <NextPhaseNotice
        screen="Vehicle detail"
        contents={[
          "Header with VIN, customer, model, odometer and status",
          "A component health strip: one card per tracked part with a radial health gauge",
          "Selecting a component reveals its 10-week probability trend against the alert threshold",
          "Signal driver bars showing what is pushing the score",
          "The degradation curve, split into observed and projected, with the failure threshold marked",
          "Service history timeline, and the cross-check tying probability to remaining life",
          "Draft outreach and create work order actions",
        ]}
        endpoints={[
          "GET /api/vehicles/{vin}",
          "GET /api/predictions/{vin}/{part}",
          "GET /api/rul/{vin}/{part}",
          "POST /api/chat/draft",
        ]}
      />
    </>
  );
}
