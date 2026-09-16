import React from "react";

export function Icon({ name, size = 16, className }) {
  return React.createElement("svg", {
    "data-icon": name,
    width: size,
    height: size,
    className: className || "icon",
    "aria-hidden": "true",
  });
}

export const ICON_NAMES = [];
