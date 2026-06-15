"use client";

import React, { useState, useCallback } from "react";
import { SubAgentIndicator } from "@/app/components/SubAgentIndicator";
import { ToolCallBox } from "@/app/components/ToolCallBox";
import { MarkdownContent } from "@/app/components/MarkdownContent";
import type { ToolCall, ActionRequest, ReviewConfig } from "@/app/types/types";
import { Message } from "@langchain/langgraph-sdk";
import type {
  SubagentStreamInterface,
  ToolCallWithResult,
} from "@langchain/langgraph-sdk/react";
import {
  extractSubAgentContent,
  extractStringFromMessageContent,
} from "@/app/utils/utils";
import { cn } from "@/lib/utils";

interface ChatMessageProps {
  message: Message;
  toolCalls: ToolCall[];
  subAgents?: SubagentStreamInterface[];
  isLoading?: boolean;
  actionRequestsMap?: Map<string, ActionRequest>;
  reviewConfigsMap?: Map<string, ReviewConfig>;
  ui?: any[];
  stream?: any;
  onResumeInterrupt?: (value: any) => void;
  graphId?: string;
}

/**
 * Преобразует streamed tool call sub-agent в формат карточки UI.
 *
 * @param toolCall Вызов инструмента из sub-agent stream.
 * @returns Нормализованный вызов инструмента с аргументами, статусом и результатом.
 */
function normalizeSubagentToolCall(toolCall: ToolCallWithResult): ToolCall {
  const call = toolCall.call ?? {};
  return {
    id: toolCall.id,
    name: call.name ?? "unknown",
    args: call.args ?? {},
    result: toolCall.result
      ? extractStringFromMessageContent(toolCall.result)
      : undefined,
    status:
      toolCall.state === "completed"
        ? "completed"
        : toolCall.state === "error"
        ? "error"
        : "pending",
  };
}

export const ChatMessage = React.memo<ChatMessageProps>(
  ({
    message,
    toolCalls,
    subAgents = [],
    isLoading,
    actionRequestsMap,
    reviewConfigsMap,
    ui,
    stream,
    onResumeInterrupt,
    graphId,
  }) => {
    const isUser = message.type === "human";
    const messageContent = extractStringFromMessageContent(message);
    const hasContent = messageContent && messageContent.trim() !== "";
    const hasToolCalls = toolCalls.length > 0;
    const [expandedSubAgents, setExpandedSubAgents] = useState<
      Record<string, boolean>
    >({});
    const isSubAgentExpanded = useCallback(
      (id: string) => expandedSubAgents[id] ?? true,
      [expandedSubAgents]
    );
    const toggleSubAgent = useCallback((id: string) => {
      setExpandedSubAgents((prev) => ({
        ...prev,
        [id]: prev[id] === undefined ? false : !prev[id],
      }));
    }, []);

    return (
      <div
        className={cn(
          "flex w-full max-w-full overflow-x-hidden",
          isUser && "flex-row-reverse"
        )}
      >
        <div
          className={cn(
            "min-w-0 max-w-full",
            isUser ? "max-w-[70%]" : "w-full"
          )}
        >
          {hasContent && (
            <div className={cn("relative flex items-end gap-0")}>
              <div
                className={cn(
                  "mt-4 overflow-hidden break-words text-sm font-normal leading-[150%]",
                  isUser
                    ? "rounded-xl rounded-br-none border border-border px-3 py-2 text-foreground"
                    : "text-primary"
                )}
                style={
                  isUser
                    ? { backgroundColor: "var(--color-user-message-bg)" }
                    : undefined
                }
              >
                {isUser ? (
                  <p className="m-0 whitespace-pre-wrap break-words text-sm leading-relaxed">
                    {messageContent}
                  </p>
                ) : hasContent ? (
                  <MarkdownContent content={messageContent} />
                ) : null}
              </div>
            </div>
          )}
          {hasToolCalls && (
            <div className="mt-4 flex w-full flex-col">
              {toolCalls.map((toolCall: ToolCall) => {
                if (toolCall.name === "task") return null;
                const toolCallGenUiComponent = ui?.find(
                  (u) => u.metadata?.tool_call_id === toolCall.id
                );
                const actionRequest = actionRequestsMap?.get(toolCall.name);
                const reviewConfig = reviewConfigsMap?.get(toolCall.name);
                return (
                  <ToolCallBox
                    key={toolCall.id}
                    toolCall={toolCall}
                    uiComponent={toolCallGenUiComponent}
                    stream={stream}
                    graphId={graphId}
                    actionRequest={actionRequest}
                    reviewConfig={reviewConfig}
                    onResume={onResumeInterrupt}
                    isLoading={isLoading}
                  />
                );
              })}
            </div>
          )}
          {!isUser && subAgents.length > 0 && (
            <div className="flex w-fit max-w-full flex-col gap-4">
              {subAgents.map((subAgent) => (
                <div
                  key={subAgent.id}
                  className="flex w-full flex-col gap-2"
                >
                  <div className="flex items-end gap-2">
                    <div className="w-[calc(100%-100px)]">
                      <SubAgentIndicator
                        name={
                          subAgent.toolCall.args.subagent_type ?? "subagent"
                        }
                        status={subAgent.status}
                        onClick={() => toggleSubAgent(subAgent.id)}
                        isExpanded={isSubAgentExpanded(subAgent.id)}
                      />
                    </div>
                  </div>
                  {isSubAgentExpanded(subAgent.id) && (
                    <div className="w-full max-w-full">
                      <div className="bg-surface border-border-light rounded-md border p-4">
                        <h4 className="text-primary/70 mb-2 text-xs font-semibold uppercase tracking-wider">
                          Задача
                        </h4>
                        <div className="mb-4">
                          <MarkdownContent
                            content={extractSubAgentContent(
                              subAgent.toolCall.args
                            )}
                          />
                        </div>
                        {subAgent.toolCalls.length > 0 && (
                          <div className="mb-4">
                            <h4 className="text-primary/70 mb-2 text-xs font-semibold uppercase tracking-wider">
                              Инструменты
                            </h4>
                            <div className="flex flex-col gap-1">
                              {subAgent.toolCalls.map((toolCall) => (
                                <ToolCallBox
                                  key={toolCall.id}
                                  toolCall={normalizeSubagentToolCall(toolCall)}
                                  isLoading={subAgent.status === "running"}
                                />
                              ))}
                            </div>
                          </div>
                        )}
                        {subAgent.messages.length > 0 && (
                          <div className="mb-4">
                            <h4 className="text-primary/70 mb-2 text-xs font-semibold uppercase tracking-wider">
                              Прогресс
                            </h4>
                            {subAgent.messages
                              .filter((item) => item.type === "ai")
                              .map((item, index) => (
                                <MarkdownContent
                                  key={item.id ?? index}
                                  content={extractStringFromMessageContent(
                                    item
                                  )}
                                />
                              ))}
                          </div>
                        )}
                        {subAgent.result && (
                          <>
                            <h4 className="text-primary/70 mb-2 text-xs font-semibold uppercase tracking-wider">
                              Результат
                            </h4>
                            <MarkdownContent content={subAgent.result} />
                          </>
                        )}
                      </div>
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    );
  }
);

ChatMessage.displayName = "ChatMessage";
