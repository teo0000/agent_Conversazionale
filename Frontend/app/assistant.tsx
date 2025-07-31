"use client";

import { AssistantRuntimeProvider } from "@assistant-ui/react";
import { Thread } from "@/components/assistant-ui/thread";
import React, { useState } from "react";
import AnimatedAvatar from "@/components/assistant-ui/AnimatedAvatar";
import { useChatRuntime } from "@assistant-ui/react-ai-sdk";

const avatarId = "68722574bf6cc44ef5b3e85f";
const avatarUrl = `https://models.readyplayer.me/${avatarId}.glb`;

export const Assistant = () => {
  const runtime = useChatRuntime({
    api: "/api/chat",
  });
  // Lo stato adella chat vocale viene gestito dal Thread
  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <div className="grid h-dvh grid-cols-[220px_1fr] gap-x-2 px-4 py-4">
        <div className="flex flex-col items-center justify-center">
          {/* AnimatedAvatar: passa isSpeaking=true per test, poi collega allo stato reale */}
          <AnimatedAvatar isSpeaking={true} />
        </div>
        <div className="flex flex-col h-full">
          <Thread />
        </div>
      </div>
    </AssistantRuntimeProvider>
  );
};
