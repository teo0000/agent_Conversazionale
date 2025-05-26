"use client";

import { AssistantRuntimeProvider } from "@assistant-ui/react";
import { useChatRuntime } from "@assistant-ui/react-ai-sdk";
import { Thread } from "@/components/assistant-ui/thread";
import { ThreadList } from "@/components/assistant-ui/thread-list";
import React from "react";

export const Assistant = () => {
  const runtime = useChatRuntime({
    api: "/api/chat",
  });
  // Lo stato della chat vocale viene gestito dal Thread
  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <div className="grid h-dvh grid-cols-[200px_1fr] gap-x-2 px-4 py-4">
        <ThreadList />
        <div className="flex flex-col h-full">
          <Thread />
        </div>
      </div>
    </AssistantRuntimeProvider>
  );
};
