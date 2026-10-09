import { createBrowserRouter } from "react-router";
import { RouterProvider } from "react-router/dom";
import { AppLayout } from "./layouts/AppLayout";
import { NotFoundPage } from "./pages/NotFoundPage";
import { OverviewPage } from "./pages/OverviewPage";
import { DonorsPage } from "./pages/DonorsPage";
import { PatientsPage } from "./pages/PatientsPage";

const router = createBrowserRouter([
  {
    path: "/",
    element: <AppLayout />,
    // Rendered while a directly-opened lazy route loads (avoids React Router's hydration warning).
    HydrateFallback: () => null,
    children: [
      { index: true, element: <OverviewPage /> },
      { path: "patients", element: <PatientsPage /> },
      {
        path: "patients/:patientCode/digital-twin",
        // Loaded on demand: this page carries the charting library.
        lazy: () => import("./pages/DigitalTwinPage").then((m) => ({ Component: m.DigitalTwinPage })),
      },
      { path: "donors", element: <DonorsPage /> },
      {
        path: "donors/:donorCode",
        lazy: () => import("./pages/DonorStatePage").then((m) => ({ Component: m.DonorStatePage })),
      },
      {
        path: "requests/:requestCode/matching",
        lazy: () => import("./pages/MatchingPage").then((m) => ({ Component: m.MatchingPage })),
      },
      {
        path: "requests/:requestCode/cascade",
        lazy: () => import("./pages/CascadePage").then((m) => ({ Component: m.CascadePage })),
      },
      {
        path: "learning",
        lazy: () => import("./pages/LearningPage").then((m) => ({ Component: m.LearningPage })),
      },
      {
        path: "notifications",
        lazy: () => import("./pages/NotificationsPage").then((m) => ({ Component: m.NotificationsPage })),
      },
      { path: "*", element: <NotFoundPage /> },
    ],
  },
]);

export default function App() {
  return <RouterProvider router={router} />;
}
