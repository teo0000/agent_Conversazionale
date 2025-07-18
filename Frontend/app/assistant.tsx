"use client";

import { AssistantRuntimeProvider } from "@assistant-ui/react";
import { Thread } from "@/components/assistant-ui/thread"; 
import React, { useState } from "react";
import { AnimatedAvatar } from "@/components/assistant-ui/AnimatedAvatar";
import { useChatRuntime } from "@assistant-ui/react-ai-sdk";

export const Assistant = () => {
  const runtime = useChatRuntime({
    api: "/api/chat",
  });
  // Lo stato della chat vocale viene gestito dal Thread
  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <div className="grid h-dvh grid-cols-[220px_1fr] gap-x-2 px-4 py-4">
        <div className="relative h-full">
          <AnimatedAvatar
            className="h-full w-full rounded-full"
            objectFit="contain"
            // Assicurati che il video sia nella cartella /public
            videoUrl="/avatar-video.mp4" 
            onVideoEnd={() => {
              // handle video end event
            }}
          />
        </div>
        <div className="flex flex-col h-full">
          <Thread />
        </div>
      </div>
    </AssistantRuntimeProvider>
  );
};
