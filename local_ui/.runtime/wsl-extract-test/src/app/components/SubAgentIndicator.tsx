"use client";

import React from "react";
import { Button } from "@/components/ui/button";
import {
  AlertCircle,
  CheckCircle,
  ChevronDown,
  ChevronUp,
  Clock,
  Loader2,
} from "lucide-react";

interface SubAgentIndicatorProps {
  name: string;
  status: "pending" | "running" | "complete" | "error";
  onClick: () => void;
  isExpanded?: boolean;
}

/**
 * Возвращает индикатор lifecycle-статуса sub-agent.
 *
 * @param status Текущий статус выполнения sub-agent.
 * @returns Иконка ожидания, выполнения, завершения или ошибки.
 */
function getSubagentStatusIcon(
  status: SubAgentIndicatorProps["status"]
): React.ReactNode {
  switch (status) {
    case "running":
      return (
        <Loader2
          size={14}
          className="animate-spin"
        />
      );
    case "complete":
      return (
        <CheckCircle
          size={14}
          className="text-success/80"
        />
      );
    case "error":
      return (
        <AlertCircle
          size={14}
          className="text-destructive"
        />
      );
    default:
      return (
        <Clock
          size={14}
          className="text-muted-foreground"
        />
      );
  }
}

export const SubAgentIndicator = React.memo<SubAgentIndicatorProps>(
  ({ name, status, onClick, isExpanded = true }) => {
    return (
      <div className="w-fit max-w-[70vw] overflow-hidden rounded-lg border-none bg-card shadow-none outline-none">
        <Button
          variant="ghost"
          size="sm"
          onClick={onClick}
          className="flex w-full items-center justify-between gap-2 border-none px-4 py-2 text-left shadow-none outline-none transition-colors duration-200"
        >
          <div className="flex w-full items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              {getSubagentStatusIcon(status)}
              <span className="font-sans text-[15px] font-bold leading-[140%] tracking-[-0.6px] text-[#3F3F46]">
                {name}
              </span>
              <span className="text-xs text-muted-foreground">{status}</span>
            </div>
            {isExpanded ? (
              <ChevronUp
                size={14}
                className="shrink-0 text-[#70707B]"
              />
            ) : (
              <ChevronDown
                size={14}
                className="shrink-0 text-[#70707B]"
              />
            )}
          </div>
        </Button>
      </div>
    );
  }
);

SubAgentIndicator.displayName = "SubAgentIndicator";
