/**
 * Routing.
 *
 * Every screen is lazily loaded and every one sits inside `AppShell`, so the
 * chrome - navigation, scope switcher, search, alerts - is constant and only
 * the content area changes between routes. The vehicle detail route is a real
 * URL rather than only a drawer: an operator has to be able to send a colleague
 * a link to one truck.
 */

import { lazy, Suspense } from "react";
import { Route, Routes } from "react-router-dom";

import { AppShell } from "@/components/layout/AppShell";
import { SkeletonCard, SkeletonKpiRow } from "@/components/ui/Skeleton";

const CommandCentre = lazy(() => import("@/pages/CommandCentre"));
const Fleet = lazy(() => import("@/pages/Fleet"));
const VehicleDetail = lazy(() => import("@/pages/VehicleDetail"));
const RulExplorer = lazy(() => import("@/pages/RulExplorer"));
const RuleStudio = lazy(() => import("@/pages/RuleStudio"));
const Alerts = lazy(() => import("@/pages/Alerts"));
const Analytics = lazy(() => import("@/pages/Analytics"));
const NotFound = lazy(() => import("@/pages/NotFound"));

/** What a route shows while its chunk downloads. Skeletons, never a spinner -
 *  the layout is known before the data is. */
function RouteFallback() {
  return (
    <div className="space-y-6">
      <SkeletonKpiRow />
      <div className="grid gap-4 lg:grid-cols-3">
        <SkeletonCard className="lg:col-span-2" />
        <SkeletonCard />
      </div>
    </div>
  );
}

export function AppRoutes() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route
          path="/"
          element={
            <Suspense fallback={<RouteFallback />}>
              <CommandCentre />
            </Suspense>
          }
        />
        <Route
          path="/fleet"
          element={
            <Suspense fallback={<RouteFallback />}>
              <Fleet />
            </Suspense>
          }
        />
        <Route
          path="/fleet/:vin"
          element={
            <Suspense fallback={<RouteFallback />}>
              <VehicleDetail />
            </Suspense>
          }
        />
        <Route
          path="/rul"
          element={
            <Suspense fallback={<RouteFallback />}>
              <RulExplorer />
            </Suspense>
          }
        />
        <Route
          path="/rules"
          element={
            <Suspense fallback={<RouteFallback />}>
              <RuleStudio />
            </Suspense>
          }
        />
        <Route
          path="/alerts"
          element={
            <Suspense fallback={<RouteFallback />}>
              <Alerts />
            </Suspense>
          }
        />
        <Route
          path="/analytics"
          element={
            <Suspense fallback={<RouteFallback />}>
              <Analytics />
            </Suspense>
          }
        />
        <Route
          path="*"
          element={
            <Suspense fallback={<RouteFallback />}>
              <NotFound />
            </Suspense>
          }
        />
      </Route>
    </Routes>
  );
}
