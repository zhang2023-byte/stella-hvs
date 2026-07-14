import "@testing-library/jest-dom/vitest";

class TestResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}

Object.defineProperty(globalThis, "ResizeObserver", { value: TestResizeObserver, writable: true });
Object.defineProperty(globalThis, "DOMMatrixReadOnly", {
  value: class DOMMatrixReadOnly {
    m22 = 1;
    constructor(_: string) {}
  },
  writable: true,
});
