/**
 * The top bar: scope switcher, global search, dark mode, notifications,
 * account.
 *
 * Scope sits on the far left, next to the navigation, because it changes what
 * every other control on the page means. Search takes the middle because it is
 * the most-used control; the status affordances sit right, where they can be
 * ignored until they matter.
 */

import { Menu as MenuIcon, Moon, Sun } from "lucide-react";

import { GlobalSearch } from "./GlobalSearch";
import { NotificationBell } from "./NotificationBell";
import { ScopeSwitcher } from "./ScopeSwitcher";
import { UserMenu } from "./UserMenu";
import { IconButton } from "@/components/ui/Button";
import { useTheme } from "@/state/theme";

export function TopBar({ onOpenNav }: { onOpenNav: () => void }) {
  const { resolved, toggle } = useTheme();

  return (
    <header className="sticky top-0 z-30 flex h-14 items-center gap-3 border-b border-hairline bg-canvas/85 px-4 backdrop-blur-md">
      <IconButton
        icon={MenuIcon}
        label="Open navigation"
        onClick={onOpenNav}
        className="lg:hidden"
      />

      <ScopeSwitcher />

      <GlobalSearch className="ml-auto w-full max-w-md lg:ml-2 lg:mr-auto" />

      <div className="flex shrink-0 items-center gap-1">
        <IconButton
          icon={resolved === "dark" ? Sun : Moon}
          label={resolved === "dark" ? "Switch to light mode" : "Switch to dark mode"}
          onClick={toggle}
        />
        <NotificationBell />
        <UserMenu />
      </div>
    </header>
  );
}
