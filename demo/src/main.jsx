import React from "react";
import { createRoot } from "react-dom/client";
import { ProjectApp as App } from "./ProjectApp";
import "./styles.css";
import "./minutes.css";

createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);

