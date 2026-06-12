/** Language model construction for Sarma runtimes. */

import { ChatAnthropic } from "@langchain/anthropic";
import { ChatOpenAI } from "@langchain/openai";
import type { BaseChatModel } from "@langchain/core/language_models/chat_models";
import { ProviderNotConfiguredError } from "@/engine/errors";
import type { ResolvedSkill } from "@/engine/models";
import type { ModelProviderDTO } from "@/engine/dto";

export interface ModelBuildParams {
  modelName: string;
  apiKey: string;
  baseUrl: string;
  temperature: number;
  topP: number;
}

/**
 * Preserve reasoning_content for OpenAI-compatible thinking models
 * (DeepSeek-R1 etc.).
 *
 * The Python implementation subclasses ChatOpenAI and patches three private
 * hooks. In LangChain.js, recent `@langchain/openai` already surfaces
 * `reasoning_content` into `additional_kwargs`/`response_metadata` on both
 * full results and stream chunks for OpenAI-compatible endpoints, and the
 * outgoing re-injection of prior reasoning is handled at the message layer
 * (`ConversationMessage.toLangchainMessage` stores it in `additional_kwargs`).
 * We therefore construct a stock ChatOpenAI here and rely on those layers.
 */
function buildOpenAiModel(params: ModelBuildParams): BaseChatModel {
  const config: Record<string, unknown> = {};
  if (params.baseUrl) config.baseURL = params.baseUrl;
  return new ChatOpenAI({
    model: params.modelName,
    temperature: params.temperature,
    topP: params.topP,
    ...(params.apiKey ? { apiKey: params.apiKey } : {}),
    ...(Object.keys(config).length ? { configuration: config } : {}),
  });
}

function buildOpenAiResponsesModel(params: ModelBuildParams): BaseChatModel {
  const config: Record<string, unknown> = {};
  if (params.baseUrl) config.baseURL = params.baseUrl;
  return new ChatOpenAI({
    model: params.modelName,
    temperature: params.temperature,
    topP: params.topP,
    useResponsesApi: true,
    ...(params.apiKey ? { apiKey: params.apiKey } : {}),
    ...(Object.keys(config).length ? { configuration: config } : {}),
  });
}

function buildAnthropicModel(params: ModelBuildParams): BaseChatModel {
  return new ChatAnthropic({
    model: params.modelName,
    temperature: params.temperature,
    topP: params.topP,
    ...(params.apiKey ? { apiKey: params.apiKey } : {}),
    ...(params.baseUrl ? { anthropicApiUrl: params.baseUrl } : {}),
  });
}

const MODEL_BUILDERS: Record<string, (p: ModelBuildParams) => BaseChatModel> = {
  openai_responses: buildOpenAiResponsesModel,
  openai_compatible: buildOpenAiModel,
  anthropic: buildAnthropicModel,
};

/** Build provider-backed LangChain chat models. */
export class ModelFactory {
  initModel(provider: ModelProviderDTO, skill: ResolvedSkill | null = null): BaseChatModel {
    const apiMode = provider.apiMode;
    const builder = MODEL_BUILDERS[apiMode];
    if (builder === undefined) {
      throw new ProviderNotConfiguredError(`Unsupported api_mode: '${apiMode}'`);
    }

    const modelName =
      skill && skill.preferredModelName ? skill.preferredModelName : provider.modelName;

    let temperature = provider.temperature;
    if (skill && skill.temperatureOverride !== null && skill.temperatureOverride !== undefined) {
      temperature = skill.temperatureOverride;
    }

    return builder({
      modelName,
      apiKey: provider.apiKey,
      baseUrl: provider.baseUrl,
      temperature,
      topP: provider.topP,
    });
  }
}
