import React from "react";
import {
  ActionBarPrimitive,
  BranchPickerPrimitive,
  ComposerPrimitive,
  MessagePrimitive,
  ThreadPrimitive,
} from "@assistant-ui/react";
import type { FC } from "react";
import {
  ArrowDownIcon,
  CheckIcon,
  ChevronLeftIcon,
  ChevronRightIcon,
  CopyIcon,
  MicIcon,
  PencilIcon,
  RefreshCwIcon,
  SendHorizontalIcon,
} from "lucide-react";
import { cn } from "@/lib/utils";

import { Button } from "@/components/ui/button";
import { MarkdownText } from "@/components/assistant-ui/markdown-text";
import { TooltipIconButton } from "@/components/assistant-ui/tooltip-icon-button";
import VoiceChat from "../assistant-ui/VoiceChat";

export const Thread: FC = () => {
  const [showVoiceChat, setShowVoiceChat] = React.useState(false);
  const [recording, setRecording] = React.useState(false);
  const [responseText, setResponseText] = React.useState<string | null>(null);
  // Stato per evitare doppio invio vocale
  const [lastSentVoiceText, setLastSentVoiceText] = React.useState<string | null>(null);

  // Stato dei messaggi della chat
  const [messages, setMessages] = React.useState<{ role: string; content: string }[]>([]);

  // Funzione per aggiungere un messaggio utente
  const addUserMessage = (message: string) => {
    setMessages((prev) => [...prev, { role: "user", content: message }]);
  };

  // Funzione per aggiungere un messaggio assistente
  const addAssistantMessage = (message: string) => {
    setMessages((prev) => [...prev, { role: "assistant", content: message }]);
  };

  // Funzione per aggiungere un messaggio di errore
  const addErrorMessage = (message: string) => {
    setMessages((prev) => [...prev, { role: "error", content: message }]);
  };

  // Funzioni di controllo per VoiceChat
  const handleStart = () => setRecording(true);
  const handleStop = () => setRecording(false);

  // Quando la trascrizione è pronta, aggiorna lo stato
  const handleVoiceChatStop = (text?: string) => {
    setRecording(false);
    if (text !== undefined) setResponseText(text);
  };

  return (
    <ThreadPrimitive.Root
      className="bg-background box-border flex h-full flex-col overflow-hidden"
      style={{
        ["--thread-max-width" as string]: "42rem",
      }}
    >
      <ThreadPrimitive.Viewport className="flex h-full flex-col items-center overflow-y-scroll scroll-smooth bg-inherit px-4 pt-8">
        <ThreadWelcome />

        {/* <ThreadPrimitive.Messages
          components={{
            UserMessage: UserMessage,
            EditComposer: EditComposer,
            AssistantMessage: AssistantMessage,
          }}
        /> */}
        {/* Rendering personalizzato dei messaggi */}
        {messages.map((msg, idx) => {
          if (msg.role === "user") {
            return (
              <div key={idx} className="flex justify-end w-full max-w-[var(--thread-max-width)] py-4">
                <div className="bg-muted text-foreground max-w-[calc(var(--thread-max-width)*0.8)] break-words rounded-3xl px-5 py-2.5">
                  {msg.content}
                </div>
              </div>
            );
          } else if (msg.role === "assistant") {
            return (
              <div key={idx} className="flex justify-start w-full max-w-[var(--thread-max-width)] py-4">
                <div className="text-foreground bg-blue-100 dark:bg-blue-900 max-w-[calc(var(--thread-max-width)*0.8)] break-words leading-7 rounded-3xl px-5 py-2.5">
                  {msg.content}
                </div>
              </div>
            );
          } else if (msg.role === "error") {
            return (
              <div key={idx} className="w-full max-w-[var(--thread-max-width)] py-4 flex justify-center">
                <div className="bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200 max-w-[calc(var(--thread-max-width)*0.8)] break-words rounded-3xl px-5 py-2.5 text-center border border-red-300 dark:border-red-700">
                  {msg.content}
                </div>
              </div>
            );
          }
          return null;
        })}

        <ThreadPrimitive.If empty={false}>
          <div className="min-h-8 flex-grow" />
        </ThreadPrimitive.If>

        <div className="sticky bottom-0 mt-3 flex w-full max-w-[var(--thread-max-width)] flex-col items-center justify-end rounded-t-lg bg-inherit pb-4">
          <ThreadScrollToBottom />
          <Composer
            onVoiceClick={() => {
              setShowVoiceChat((v) => {
                const next = !v;
                if (!v) setRecording(true);
                else setRecording(false);
                return next;
              });
            }}
            voiceActive={showVoiceChat}
            recording={recording}
            onStart={handleStart}
            onStop={handleStop}
            responseText={responseText}
          />
        </div>
      </ThreadPrimitive.Viewport>

      {showVoiceChat && (
        <VoiceChat
          recording={recording}
          onStart={handleStart}
          onStop={handleStop}
          responseText={responseText}
          setResponseText={setResponseText}
          addUserMessage={addUserMessage}
          addAssistantMessage={addAssistantMessage}
          addErrorMessage={addErrorMessage}
          lastSentVoiceText={lastSentVoiceText}
          setLastSentVoiceText={setLastSentVoiceText}
        />
      )}
    </ThreadPrimitive.Root>
  );
};

const ThreadScrollToBottom: FC = () => {
  return (
    <ThreadPrimitive.ScrollToBottom asChild>
      <TooltipIconButton
        tooltip="Scroll to bottom"
        variant="outline"
        className="absolute -top-8 rounded-full disabled:invisible"
      >
        <ArrowDownIcon />
      </TooltipIconButton>
    </ThreadPrimitive.ScrollToBottom>
  );
};

const ThreadWelcome: FC = () => {
  return (
    <ThreadPrimitive.Empty>
      <div className="flex w-full max-w-[var(--thread-max-width)] flex-grow flex-col items-center justify-center">
        <div className="bg-white/90 dark:bg-zinc-900/80 shadow-lg rounded-2xl p-8 flex flex-col items-center animate-fade-in-up transition-all duration-700 mt-16">
          <div className="bg-blue-100 dark:bg-blue-900 rounded-full p-3 mb-4">
            <svg width="40" height="40" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
              <circle cx="12" cy="12" r="12" fill="#2563eb" fillOpacity="0.15" />
              <path d="M12 7a3 3 0 0 1 3 3v1a3 3 0 0 1-6 0v-1a3 3 0 0 1 3-3zm0 10c-2.67 0-8 1.34-8 4v1h16v-1c0-2.66-5.33-4-8-4z" fill="#2563eb" />
            </svg>
          </div>
          <h2 className="text-xl font-bold text-center mb-2 text-blue-700 dark:text-blue-300">Ciao! Sono il tuo assistente virtuale.</h2>
          <p className="text-center text-base text-zinc-700 dark:text-zinc-200 max-w-lg">
            Posso gestire le tue prenotazioni:<br />
            <span className="font-semibold">Il servizio è operativo dalle 08:00 alle 18:00</span><br />
            (l’ultima fascia è dalle 17:00 alle 18:00, quindi alle 18:00 non si accettano nuove richieste).<br />
            <span className="block mt-2">Come posso supportarti oggi?</span>
          </p>
        </div>
        <ThreadWelcomeSuggestions />
      </div>
    </ThreadPrimitive.Empty>
  );
};

const ThreadWelcomeSuggestions: FC = () => {
  return (
    <div className="mt-3 flex w-full items-stretch justify-center gap-4">
      <ThreadPrimitive.Suggestion
        className="hover:bg-muted/80 flex max-w-sm grow basis-0 flex-col items-center justify-center rounded-lg border p-3 transition-colors ease-in"
        prompt="Prenotami una sala per domani"
        method="replace"
        autoSend
      >
        <span className="line-clamp-2 text-ellipsis text-sm font-semibold">
          Prenota una sala per domani
        </span>
      </ThreadPrimitive.Suggestion>

    </div>
  );
};

const Composer: FC<{ onVoiceClick?: () => void; voiceActive?: boolean; recording?: boolean; onStart?: () => void; onStop?: () => void; responseText?: string | null }> = ({ onVoiceClick, voiceActive, recording, onStart, onStop, responseText }) => {
  return (
    <ComposerPrimitive.Root className="focus-within:border-ring/20 flex w-full flex-wrap items-end rounded-lg border bg-inherit px-2.5 shadow-sm transition-colors ease-in">
      <ComposerPrimitive.Input
        rows={1}
        autoFocus
        placeholder={recording ? "Sto registrando..." : "Write a message..."}
        className="placeholder:text-muted-foreground max-h-40 flex-grow resize-none border-none bg-transparent px-2 py-4 text-sm outline-none focus:ring-0 disabled:cursor-not-allowed"
      />
      <ComposerAction onVoiceClick={onVoiceClick} voiceActive={voiceActive} recording={recording} onStart={onStart} onStop={onStop} />
      {responseText && (
        <div className="w-full text-xs text-blue-700 dark:text-blue-300 mt-2 px-2">
          <b>Testo interpretato:</b> {responseText}
        </div>
      )}
    </ComposerPrimitive.Root>
  );
};

const ComposerAction: FC<{ onVoiceClick?: () => void; voiceActive?: boolean; recording?: boolean; onStart?: () => void; onStop?: () => void; }> = ({ onVoiceClick, voiceActive, recording }) => {
  return (
    <>
      <TooltipIconButton
        tooltip={voiceActive ? "Nascondi chat vocale" : "Attiva chat vocale"}
        aria-label={voiceActive ? "Nascondi chat vocale" : "Attiva chat vocale"}
        onClick={e => { console.log('Microfono cliccato'); onVoiceClick && onVoiceClick(); }}
        variant={voiceActive ? "default" : "ghost"}
        className={`my-2.5 size-8 p-2 flex items-center justify-center rounded-full transition-all duration-300 ease-in
          ${recording ? 'scale-110 ring-2 ring-primary shadow-lg' : 'shadow-xs'}
          bg-primary text-primary-foreground hover:bg-primary/90 mr-2`}
        style={{ transform: recording ? 'scale(1.10)' : 'scale(1)' }}
      >
        <MicIcon className={`size-5 transition-all duration-300`} />
      </TooltipIconButton>
      <ThreadPrimitive.If running={false}>
        <ComposerPrimitive.Send asChild>
          <TooltipIconButton
            tooltip="Send"
            variant="default"
            className="my-2.5 size-8 p-2 transition-opacity ease-in"
          >
            <SendHorizontalIcon />
          </TooltipIconButton>
        </ComposerPrimitive.Send>
      </ThreadPrimitive.If>
      <ThreadPrimitive.If running>
        <ComposerPrimitive.Cancel asChild>
          <TooltipIconButton
            tooltip="Cancel"
            variant="default"
            className="my-2.5 size-8 p-2 transition-opacity ease-in"
          >
            <CircleStopIcon />
          </TooltipIconButton>
        </ComposerPrimitive.Cancel>
      </ThreadPrimitive.If>
    </>
  );
};

const UserMessage: FC = () => {
  return (
    <MessagePrimitive.Root className="grid auto-rows-auto grid-cols-[minmax(72px,1fr)_auto] gap-y-2 [&:where(>*)]:col-start-2 w-full max-w-[var(--thread-max-width)] py-4">
      <UserActionBar />

      <div className="bg-muted text-foreground max-w-[calc(var(--thread-max-width)*0.8)] break-words rounded-3xl px-5 py-2.5 col-start-2 row-start-2">
        <MessagePrimitive.Content />
      </div>

      <BranchPicker className="col-span-full col-start-1 row-start-3 -mr-1 justify-end" />
    </MessagePrimitive.Root>
  );
};

const UserActionBar: FC = () => {
  return (
    <ActionBarPrimitive.Root
      hideWhenRunning
      autohide="not-last"
      className="flex flex-col items-end col-start-1 row-start-2 mr-3 mt-2.5"
    >
      <ActionBarPrimitive.Edit asChild>
        <TooltipIconButton tooltip="Edit">
          <PencilIcon />
        </TooltipIconButton>
      </ActionBarPrimitive.Edit>
    </ActionBarPrimitive.Root>
  );
};

const EditComposer: FC = () => {
  return (
    <ComposerPrimitive.Root className="bg-muted my-4 flex w-full max-w-[var(--thread-max-width)] flex-col gap-2 rounded-xl">
      <ComposerPrimitive.Input className="text-foreground flex h-8 w-full resize-none bg-transparent p-4 pb-0 outline-none" />

      <div className="mx-3 mb-3 flex items-center justify-center gap-2 self-end">
        <ComposerPrimitive.Cancel asChild>
          <Button variant="ghost">Cancel</Button>
        </ComposerPrimitive.Cancel>
        <ComposerPrimitive.Send asChild>
          <Button>Send</Button>
        </ComposerPrimitive.Send>
      </div>
    </ComposerPrimitive.Root>
  );
};

const AssistantMessage: FC = () => {
  return (
    <MessagePrimitive.Root className="grid grid-cols-[auto_auto_1fr] grid-rows-[auto_1fr] relative w-full max-w-[var(--thread-max-width)] py-4">
      <div className="text-foreground max-w-[calc(var(--thread-max-width)*0.8)] break-words leading-7 col-span-2 col-start-2 row-start-1 my-1.5">
        <MessagePrimitive.Content components={{ Text: MarkdownText }} />
      </div>

      <AssistantActionBar />

      <BranchPicker className="col-start-2 row-start-2 -ml-2 mr-2" />
    </MessagePrimitive.Root>
  );
};

const AssistantActionBar: FC = () => {
  return (
    <ActionBarPrimitive.Root
      hideWhenRunning
      autohide="not-last"
      autohideFloat="single-branch"
      className="text-muted-foreground flex gap-1 col-start-3 row-start-2 -ml-1 data-[floating]:bg-background data-[floating]:absolute data-[floating]:rounded-md data-[floating]:border data-[floating]:p-1 data-[floating]:shadow-sm"
    >
      <ActionBarPrimitive.Copy asChild>
        <TooltipIconButton tooltip="Copy">
          <MessagePrimitive.If copied>
            <CheckIcon />
          </MessagePrimitive.If>
          <MessagePrimitive.If copied={false}>
            <CopyIcon />
          </MessagePrimitive.If>
        </TooltipIconButton>
      </ActionBarPrimitive.Copy>
      <ActionBarPrimitive.Reload asChild>
        <TooltipIconButton tooltip="Refresh">
          <RefreshCwIcon />
        </TooltipIconButton>
      </ActionBarPrimitive.Reload>
    </ActionBarPrimitive.Root>
  );
};

const BranchPicker: FC<BranchPickerPrimitive.Root.Props> = ({
  className,
  ...rest
}) => {
  return (
    <BranchPickerPrimitive.Root
      hideWhenSingleBranch
      className={cn(
        "text-muted-foreground inline-flex items-center text-xs",
        className
      )}
      {...rest}
    >
      <BranchPickerPrimitive.Previous asChild>
        <TooltipIconButton tooltip="Previous">
          <ChevronLeftIcon />
        </TooltipIconButton>
      </BranchPickerPrimitive.Previous>
      <span className="font-medium">
        <BranchPickerPrimitive.Number /> / <BranchPickerPrimitive.Count />
      </span>
      <BranchPickerPrimitive.Next asChild>
        <TooltipIconButton tooltip="Next">
          <ChevronRightIcon />
        </TooltipIconButton>
      </BranchPickerPrimitive.Next>
    </BranchPickerPrimitive.Root>
  );
};

const CircleStopIcon = () => {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 16 16"
      fill="currentColor"
      width="16"
      height="16"
    >
      <rect width="10" height="10" x="3" y="3" rx="2" />
    </svg>
  );
};
