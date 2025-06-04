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
import { cleanTextForProcessing } from "../../lib/text-utils";

import { Button } from "@/components/ui/button";
import { MarkdownText } from "@/components/assistant-ui/markdown-text";
import { TooltipIconButton } from "@/components/assistant-ui/tooltip-icon-button";
import VoiceChat from "../assistant-ui/VoiceChat";

export const Thread: FC = () => {
  const [showVoiceChat, setShowVoiceChat] = React.useState(false);
  const [recording, setRecording] = React.useState(false);
  const [responseText, setResponseText] = React.useState<string | null>(null);
  // Stato dei messaggi della chat
  const [messages, setMessages] = React.useState<{ role: string; content: string }[]>([]);
  // Stato per il valore della textarea
  const [inputValue, setInputValue] = React.useState("");
  // Stato per mostrare il loader di caricamento (sia per voce che testo)
  const [isLoading, setIsLoading] = React.useState(false);
  const [isAudioPlaying, setIsAudioPlaying] = React.useState(false);
  const audioRef = React.useRef<HTMLAudioElement | null>(null);

  // Funzione per aggiungere un messaggio utente
  const addUserMessage = React.useCallback((message: string) => {
    setMessages(prev => {
      const updated = [...prev, { role: "user", content: message }];
      console.log("[addUserMessage] Stato aggiornato:", updated);
      return updated;
    });
  }, []);

  // Funzione per aggiungere un messaggio assistente
  const addAssistantMessage = React.useCallback((message: string) => {
    setMessages(prev => {
      const updated = [...prev, { role: "assistant", content: message }];
      console.log("[addAssistantMessage] Stato aggiornato:", updated);
      return updated;
    });
  }, []);

  // Funzione per aggiungere un messaggio di errore
  const addErrorMessage = React.useCallback((message: string) => {
    setMessages(prev => {
      const updated = [...prev, { role: "error", content: message }];
      console.log("[addErrorMessage] Stato aggiornato:", updated);
      return updated;
    });
  }, []);

  // Funzioni di controllo per VoiceChat
  const handleStart = () => setRecording(true);
  const handleStop = () => setRecording(false);

  // Funzione per inviare il messaggio (sia da testo che da voce)
  const handleSend = React.useCallback(async (message?: string, isFromVoice: boolean = false) => {
    let msgToProcess = message !== undefined ? message : inputValue;
    msgToProcess = cleanTextForProcessing(msgToProcess);
    if (msgToProcess.trim() !== "") {
      setInputValue("");
      setResponseText(null);
      setIsLoading(true);
      setMessages(prev => {
        const updated = [...prev, { role: "user", content: msgToProcess }];
        return updated;
      });
      try {
        // Costruisci la history includendo il messaggio appena aggiunto
        const currentMessagesSnapshot = [
          ...messages,
          { role: "user", content: msgToProcess }
        ];
        const historyPayload = [
          ...currentMessagesSnapshot.map(m =>
            m.role === "user"
              ? { type: "human", content: m.content }
              : m.role === "assistant"
                ? { type: "ai", content: m.content }
                : null
          ).filter(Boolean)
        ];
        const lastN = 10;
        const limitedHistory = historyPayload.slice(-lastN);

        console.log("[handleSend] Constructed 'limitedHistory' for backend:", JSON.stringify(limitedHistory, null, 2));

        const chatRes = await fetch("http://localhost:8000/agent", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            messages: limitedHistory
          }),
        });
        if (chatRes.ok) {
          const chatData = await chatRes.json();
          // Estrai il messaggio dell'assistente
          let assistantContent = null;
          if (chatData && Array.isArray(chatData.messages)) {
            const agentMsgObj = chatData.messages
              .slice()
              .reverse()
              .find((m: any) => m.type === "ai" && m.content && typeof m.content === 'string' && m.content.trim() !== "");
            if (agentMsgObj) {
              assistantContent = agentMsgObj.content;
            }
          }
          if (assistantContent) {
            // 1. Prima fetch TTS
            try {
              const ttsRes = await fetch("http://localhost:8000/agent/tts", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ text: assistantContent }),
              });
              if (ttsRes.ok) {
                const audioBlob = await ttsRes.blob();
                const audioUrl = URL.createObjectURL(audioBlob);
                // 2. Solo ora mostra il messaggio assistant nel DOM
                setMessages(prev => {
                  const updated = [...prev, { role: "assistant", content: assistantContent }];
                  return updated;
                });
                // 3. Avvia la riproduzione
                const audio = new Audio(audioUrl);
                audio.play().catch(e => console.error("Error playing TTS audio for assistant:", e));
                audio.onended = () => URL.revokeObjectURL(audioUrl);
              } else {
                setMessages(prev => {
                  const updated = [...prev, { role: "assistant", content: assistantContent }];
                  return updated;
                });
              }
            } catch (ttsErr) {
              setMessages(prev => {
                const updated = [...prev, { role: "assistant", content: assistantContent }];
                return updated;
              });
              console.error("[Thread] Error during TTS fetch operation for assistant response:", ttsErr);
            }
          } else {
            setMessages(prev => {
              const updated = [...prev, { role: "error", content: "L'assistente ha risposto, ma il formato del messaggio non è stato riconosciuto. Dati: " + JSON.stringify(chatData).substring(0, 200) + "..." }];
              return updated;
            });
          }
        } else {
          const errText = await chatRes.text();
          setMessages(prev => {
            const updated = [...prev, { role: "error", content: "Errore dal backend: " + errText }];
            return updated;
          });
        }
      } catch (err: any) {
        setMessages(prev => {
          const updated = [...prev, { role: "error", content: "Errore di rete: " + (err?.message || err) }];
          return updated;
        });
      } finally {
        setIsLoading(false);
      }
    }
  }, [inputValue, messages, addUserMessage, addAssistantMessage, addErrorMessage]);

  // Quando la trascrizione è pronta, invia il messaggio e resetta la textarea SOLO dopo l'invio
  const handleVoiceChatStop = (text?: string) => {
    setRecording(false);
    if (text !== undefined && text.trim() !== "") {
      handleSend(text); // Invia il messaggio e resetta tutto
    }
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
        {/* Se non ci sono ancora messaggi assistant, mostra il loader in fondo */}
        {/* Loader in fondo rimosso: ora il loader compare solo al posto del Composer (input) */}

        <ThreadPrimitive.If empty={false}>
          <div className="min-h-8 flex-grow" />
        </ThreadPrimitive.If>

        <div className="sticky bottom-0 mt-3 flex w-full max-w-[var(--thread-max-width)] flex-col items-start justify-end rounded-t-lg bg-inherit pb-4 pl-2">
          <ThreadScrollToBottom />
          {isLoading && (
            <div className="flex justify-start w-full items-center gap-3">
              <div className="bg-white/90 dark:bg-zinc-900/80 shadow-lg rounded-full p-2 flex flex-col items-center animate-fade-in-up transition-all duration-700 mt-2 mb-1 min-w-[56px] min-h-[56px] max-w-[56px] max-h-[56px] justify-center">
                <div className="bg-blue-100 dark:bg-blue-900 rounded-full p-1 relative flex items-center justify-center w-8 h-8">
                  <svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                    <circle cx="12" cy="12" r="12" fill="#2563eb" fillOpacity="0.15" />
                    <path d="M12 7a3 3 0 0 1 3 3v1a3 3 0 0 1-6 0v-1a3 3 0 0 1 3-3zm0 10c-2.67 0-8 1.34-8 4v1h16v-1c0-2.66-5.33-4-8-4z" fill="#2563eb" />
                  </svg>
                  {/* Spinner sopra l'avatar */}
                  <svg className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 animate-spin" width="16" height="16" viewBox="0 0 24 24">
                    <circle className="opacity-20" cx="12" cy="12" r="7" stroke="#2563eb" strokeWidth="3" fill="none" />
                    <path className="opacity-80" fill="#2563eb" d="M4 12a8 8 0 0 1 8-8v2z" />
                  </svg>
                </div>
              </div>
              <span className="text-sm font-medium text-blue-700 dark:text-blue-300 animate-pulse ml-1">Sto elaborando...</span>
            </div>
          )}
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
            inputValue={inputValue}
            setInputValue={setInputValue}
            onSend={() => handleSend()}
            disabled={isAudioPlaying}
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
          addErrorMessage={addErrorMessage}
          onAudioSendToBackend={() => {
            setRecording(false);
            setShowVoiceChat(false);
          }}
          onProcessTranscribedText={(text) => handleSend(text, true)}
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


    </div>
  );
};

// Modifica il componente Composer per gestire inputValue e setInputValue
const Composer: FC<{
  onVoiceClick?: () => void;
  voiceActive?: boolean;
  recording?: boolean;
  onStart?: () => void;
  onStop?: () => void;
  responseText?: string | null;
  inputValue: string;
  setInputValue: (v: string) => void;
  onSend: () => void;
  disabled?: boolean;
}> = ({ onVoiceClick, voiceActive, recording, onStart, onStop, responseText, inputValue, setInputValue, onSend, disabled }) => {
  return (
    <ComposerPrimitive.Root asChild>
      <form
        className="focus-within:border-ring/20 flex w-full flex-wrap items-end rounded-lg border bg-inherit px-2.5 shadow-sm transition-colors ease-in"
        onSubmit={e => {
          e.preventDefault();
          if (!disabled) onSend();
        }}
      >
        <ComposerPrimitive.Input
          rows={1}
          autoFocus
          placeholder={recording ? "Sto registrando..." : "Write a message..."}
          className="placeholder:text-muted-foreground max-h-40 flex-grow resize-none border-none bg-transparent px-2 py-4 text-sm outline-none focus:ring-0 disabled:cursor-not-allowed"
          value={inputValue}
          onChange={e => setInputValue(e.target.value)}
          name="input"
          disabled={disabled}
        />
        <ComposerAction
          onVoiceClick={onVoiceClick}
          voiceActive={voiceActive}
          recording={recording}
          inputValue={inputValue}
          disabled={disabled}
        />
        {/* Mostra il testo trascritto solo se presente */}
        {responseText && (
          <div className="w-full text-xs text-blue-700 dark:text-blue-300 mt-2 px-2">
            <b>Testo interpretato:</b> {responseText}
          </div>
        )}
      </form>
    </ComposerPrimitive.Root>
  );
};

const ComposerAction: FC<{ onVoiceClick?: () => void; voiceActive?: boolean; recording?: boolean; onStart?: () => void; onStop?: () => void; inputValue: string; disabled?: boolean; }> = ({ onVoiceClick, voiceActive, recording, inputValue, disabled }) => {
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
        type="button"
        disabled={disabled}
      >
        <MicIcon className={`size-5 transition-all duration-300`} />
      </TooltipIconButton>
      <ThreadPrimitive.If running={false}>
        {/* <ComposerPrimitive.Send asChild> */}
        <TooltipIconButton
          tooltip="Send"
          variant="default"
          className="my-2.5 size-8 p-2 transition-opacity ease-in"
          type="submit"
          disabled={!inputValue.trim() || disabled}
          tabIndex={0}
        >
          <SendHorizontalIcon />
        </TooltipIconButton>
        {/* </ComposerPrimitive.Send> */}
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

// Sposto qui la dichiarazione per evitare errori di utilizzo prima della definizione
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
