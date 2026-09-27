import { lazy, StrictMode, Suspense } from "react";
import { createRoot } from "react-dom/client";
import "maplibre-gl/dist/maplibre-gl.css";
import "./index.css";
import App from "./App";

// /bounties is a standalone page reached only by URL; its Solana code loads only there
const Bounties = lazy(() => import("./bounties/BountiesPage"));
const onBounties = window.location.pathname.replace(/\/+$/, "") === "/bounties";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    {onBounties ? <Suspense fallback={null}><Bounties /></Suspense> : <App />}
  </StrictMode>,
);
