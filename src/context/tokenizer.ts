import { encodingForModel, getEncoding } from "js-tiktoken";
import type { ProviderConfig } from "@/config";
import type { ModelProviderDTO } from "@/engine/dto";

export type TokenEstimator = (text: string) => number;

function fallbackEstimate(text: string): number {
  return Math.max(0, Math.ceil((text || "").length / 4));
}

function openAiEncodingFor(modelName: string) {
  try {
    return encodingForModel(modelName as never);
  } catch {
    return getEncoding("o200k_base");
  }
}

export function createTokenEstimator(provider: ProviderConfig | ModelProviderDTO | null): TokenEstimator {
  const modelName = provider?.modelName || "";
  const apiMode = provider?.apiMode || "openai_compatible";
  let enc: ReturnType<typeof getEncoding> | null = null;
  try {
    enc = openAiEncodingFor(modelName);
  } catch {
    enc = null;
  }
  const safety = apiMode === "anthropic" ? 1.15 : 1.0;
  return (text: string): number => {
    if (!text) return 0;
    if (!enc) return Math.ceil(fallbackEstimate(text) * safety);
    try {
      return Math.ceil(enc.encode(text).length * safety);
    } catch {
      return Math.ceil(fallbackEstimate(text) * safety);
    }
  };
}
