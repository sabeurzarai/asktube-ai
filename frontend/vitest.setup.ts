import "@testing-library/jest-dom/vitest";

// jsdom doesn't implement scrollIntoView
window.HTMLElement.prototype.scrollIntoView = vi.fn();

// Stub speechSynthesis — not available in jsdom
Object.defineProperty(window, "speechSynthesis", {
  value: {
    cancel: vi.fn(),
    speak: vi.fn(),
    getVoices: vi.fn(() => []),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  },
  writable: true,
  configurable: true,
});

// Stub SpeechSynthesisUtterance — not available in jsdom
Object.defineProperty(window, "SpeechSynthesisUtterance", {
  value: class SpeechSynthesisUtterance {
    text: string;
    rate = 1;
    pitch = 1;
    voice: null = null;
    constructor(text: string) {
      this.text = text;
    }
  },
  writable: true,
  configurable: true,
});
