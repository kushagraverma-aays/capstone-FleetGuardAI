import { Compass } from "lucide-react";
import { useNavigate } from "react-router-dom";

import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";

export default function NotFoundPage() {
  const navigate = useNavigate();

  return (
    <EmptyState
      icon={Compass}
      title="That page is not part of FleetGuard"
      description="The address does not match any screen in the product. The Command Centre has the fleet overview, and the sidebar has everything else."
      action={
        <Button variant="primary" onClick={() => navigate("/")}>
          Go to the Command Centre
        </Button>
      }
    />
  );
}
