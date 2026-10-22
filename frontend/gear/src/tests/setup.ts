import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, beforeEach, vi } from "vitest";
afterEach(cleanup);
beforeEach(() => {
  sessionStorage.clear();
  location.hash = "";
  vi.restoreAllMocks();
});
// Native dialog behavior is exercised in Chromium; jsdom lacks these methods.
HTMLDialogElement.prototype.showModal = function () {
  this.open = true;
  this.querySelector<HTMLElement>("[autofocus]")?.focus();
};
HTMLDialogElement.prototype.close = function () {
  this.open = false;
};

Object.defineProperty(window, "matchMedia", {
  writable: true,
  value: () => ({ matches: false }),
});
HTMLDialogElement.prototype.show = function () {
  this.open = true;
};
