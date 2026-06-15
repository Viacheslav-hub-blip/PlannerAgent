"use client";

import { useCallback, useState } from "react";
import { useStream } from "@langchain/langgraph-sdk/react";
import {
  type Message,
  type Assistant,
  type Checkpoint,
} from "@langchain/langgraph-sdk";
import { v4 as uuidv4 } from "uuid";
import type {
  SubagentStreamInterface,
  UseStreamThread,
} from "@langchain/langgraph-sdk/react";
import type { TodoItem } from "@/app/types/types";
import { useClient } from "@/providers/ClientProvider";
import { useQueryState } from "nuqs";
import { toast } from "sonner";

export type StateType = {
  messages: Message[];
  todos: TodoItem[];
  files: Record<string, string>;
  email?: {
    id?: string;
    subject?: string;
    page_content?: string;
  };
  ui?: any;
};

type DeepAgentStream = ReturnType<typeof useStream<StateType>> & {
  getSubagentsByMessage: (messageId: string) => SubagentStreamInterface[];
};

/**
 * Преобразует ошибку stream в безопасное сообщение для пользователя.
 *
 * @param error Ошибка LangGraph SDK или сетевого запроса.
 * @returns Короткое сообщение без внутренних деталей backend.
 */
function formatStreamError(error: unknown): string {
  const errorName =
    error instanceof Error
      ? error.name
      : typeof error === "object" && error !== null && "name" in error
        ? String(error.name)
        : "";

  if (errorName.includes("APIConnection")) {
    return "Не удалось подключиться к модели. Повторите запрос позже.";
  }
  if (errorName.includes("APIStatus")) {
    return "Провайдер модели не смог обработать запрос. Повторите запрос позже.";
  }
  return "Выполнение запроса завершилось с ошибкой. Повторите запрос позже.";
}

export function useChat({
  activeAssistant,
  onHistoryRevalidate,
  thread,
}: {
  activeAssistant: Assistant | null;
  onHistoryRevalidate?: () => void;
  thread?: UseStreamThread<StateType>;
}) {
  const [threadId, setThreadId] = useQueryState("threadId");
  const [streamError, setStreamError] = useState<string | null>(null);
  const client = useClient();

  const stream = useStream<StateType>({
    assistantId: activeAssistant?.assistant_id || "",
    client: client ?? undefined,
    reconnectOnMount: true,
    threadId: threadId ?? null,
    onThreadId: setThreadId,
    defaultHeaders: { "x-auth-scheme": "langsmith" },
    // Enable fetching state history when switching to existing threads
    fetchStateHistory: true,
    // Revalidate thread list when stream finishes, errors, or creates new thread
    onFinish: onHistoryRevalidate,
    onError: (error) => {
      const message = formatStreamError(error);
      setStreamError(message);
      toast.error(message);
      onHistoryRevalidate?.();
    },
    onCreated: onHistoryRevalidate,
  }) as DeepAgentStream;

  const sendMessage = useCallback(
    (content: string) => {
      setStreamError(null);
      const newMessage: Message = { id: uuidv4(), type: "human", content };
      stream.submit(
        { messages: [newMessage] },
        {
          streamSubgraphs: true,
          optimisticValues: (prev) => ({
            messages: [...(prev.messages ?? []), newMessage],
          }),
          config: { ...(activeAssistant?.config ?? {}), recursion_limit: 100 },
        }
      );
      // Update thread list immediately when sending a message
      onHistoryRevalidate?.();
    },
    [stream, activeAssistant?.config, onHistoryRevalidate]
  );

  const runSingleStep = useCallback(
    (
      messages: Message[],
      checkpoint?: Checkpoint,
      isRerunningSubagent?: boolean,
      optimisticMessages?: Message[]
    ) => {
      if (checkpoint) {
        stream.submit(undefined, {
          ...(optimisticMessages
            ? { optimisticValues: { messages: optimisticMessages } }
            : {}),
          config: activeAssistant?.config,
          checkpoint: checkpoint,
          streamSubgraphs: true,
          ...(isRerunningSubagent
            ? { interruptAfter: ["tools"] }
            : { interruptBefore: ["tools"] }),
        });
      } else {
        stream.submit(
          { messages },
          {
            config: activeAssistant?.config,
            interruptBefore: ["tools"],
            streamSubgraphs: true,
          }
        );
      }
    },
    [stream, activeAssistant?.config]
  );

  const setFiles = useCallback(
    async (files: Record<string, string>) => {
      if (!threadId) return;
      // TODO: missing a way how to revalidate the internal state
      // I think we do want to have the ability to externally manage the state
      await client.threads.updateState(threadId, { values: { files } });
    },
    [client, threadId]
  );

  const continueStream = useCallback(
    (hasTaskToolCall?: boolean) => {
      setStreamError(null);
      stream.submit(undefined, {
        streamSubgraphs: true,
        config: {
          ...(activeAssistant?.config || {}),
          recursion_limit: 100,
        },
        ...(hasTaskToolCall
          ? { interruptAfter: ["tools"] }
          : { interruptBefore: ["tools"] }),
      });
      // Update thread list when continuing stream
      onHistoryRevalidate?.();
    },
    [stream, activeAssistant?.config, onHistoryRevalidate]
  );

  const markCurrentThreadAsResolved = useCallback(() => {
    stream.submit(null, {
      command: { goto: "__end__", update: null },
      streamSubgraphs: true,
    });
    // Update thread list when marking thread as resolved
    onHistoryRevalidate?.();
  }, [stream, onHistoryRevalidate]);

  const resumeInterrupt = useCallback(
    (value: any) => {
      setStreamError(null);
      stream.submit(null, {
        command: { resume: value },
        streamSubgraphs: true,
      });
      // Update thread list when resuming from interrupt
      onHistoryRevalidate?.();
    },
    [stream, onHistoryRevalidate]
  );

  const stopStream = useCallback(() => {
    stream.stop();
  }, [stream]);

  return {
    stream,
    todos: stream.values.todos ?? [],
    files: stream.values.files ?? {},
    email: stream.values.email,
    ui: stream.values.ui,
    setFiles,
    messages: stream.messages,
    streamError,
    isLoading: stream.isLoading,
    isThreadLoading: stream.isThreadLoading,
    interrupt: stream.interrupt,
    getMessagesMetadata: stream.getMessagesMetadata,
    sendMessage,
    runSingleStep,
    continueStream,
    stopStream,
    markCurrentThreadAsResolved,
    resumeInterrupt,
  };
}
