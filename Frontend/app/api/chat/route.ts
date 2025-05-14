import { openai } from "@ai-sdk/openai";
import { jsonSchema, streamText, CoreMessage as VercelAICoreMessage, ToolCallPart, ToolResultPart } from "ai"; // Importa CoreMessage e altri tipi utili
import fetch from 'node-fetch'; // Importa fetch per inviare richieste HTTP

export const runtime = "nodejs"; // Cambiato in nodejs per supportare il child_process
export const maxDuration = 30;

// Definizione del tipo per la risposta del backend
interface BackendApiResponse { // Rinominato per chiarezza
  messages: Array<{ role: string; content: string }>;
}

// Non è più necessario definire CoreMessage qui, useremo VercelAICoreMessage

// Definizione del tipo per i messaggi inviati/ricevuti dal backend FastAPI
// Questo dovrebbe corrispondere a come `serialize_messages` in Python formatta i messaggi.
interface BackendMessageFormat {
  type: string; // "human", "ai", "tool", "system" (da LangChain)
  content: string;
  // Modificato per riflettere il formato ricevuto dal backend Python
  tool_calls?: Array<{
    id: string;
    name: string; // Nome della funzione al livello superiore
    args: string | Record<string, any>; // args può essere una stringa JSON o un oggetto già parsato
    type: 'tool_call' | 'function'; // Il backend invia 'tool_call', Vercel SDK si aspetta 'function' internamente
    // La struttura originale attesa era: function: { name: string; arguments: string; }
  }>;
  tool_call_id?: string;
}


// Funzione per validare e trasformare i messaggi nel formato richiesto
function validateAndNormalizeMessages(messages: Array<any>): Array<BackendMessageFormat> {
  return messages.map((message, index) => {
    // console.log(`Normalizzazione messaggio [${index}]:`, message); // Riduci verbosità

    // Trasforma il campo content in una stringa se è un array
    if (Array.isArray(message.content)) {
      message.content = message.content.map((item: { text: string }) => item.text).join(" ");
    }
    
    // Mappa il campo "type" a "role" se necessario
    if (!message.role && message.type) {
      message.role = message.type === "human" ? "user" : message.type;
    }

    if (typeof message.role !== "string" || typeof message.content !== "string") {
      throw new Error(
        `Formato messaggio non valido: ogni messaggio deve avere 'role' e 'content' come stringhe. Messaggio ricevuto: ${JSON.stringify(message)}`
      );
    }

    // Restituisce un formato più vicino a BackendMessageFormat
    return {
      type: message.role, // Usa 'role' come 'type' per coerenza con la serializzazione Python
      content: message.content,
      tool_calls: message.tool_calls,
      tool_call_id: message.tool_call_id
    } as BackendMessageFormat;
  });
}

// Funzione per trasformare i messaggi nel formato richiesto da streamText
function transformToCoreMessages(backendMessages: Array<BackendMessageFormat>): Array<VercelAICoreMessage> {
  const coreMessages: VercelAICoreMessage[] = [];
  for (const msg of backendMessages) {
    if (msg.type === "human" || msg.type === "user") { // Gestisce sia 'human' che 'user' come ruolo utente
      coreMessages.push({ role: "user", content: msg.content });
    } else if (msg.type === "system") {
      coreMessages.push({ role: "system", content: msg.content });
    } else if (msg.type === "ai" || msg.type === "assistant") {
      if (msg.tool_calls && msg.tool_calls.length > 0) {
        const toolCallParts: ToolCallPart[] = [];
        for (const tc of msg.tool_calls) {
          try {
            // Adattato per il formato ricevuto: tc.name e tc.args al livello superiore
            if (!tc || typeof tc.id !== 'string' || typeof tc.name !== 'string' || tc.args === undefined) {
              console.error("Tool call malformato o con campi mancanti (id, name, args):", JSON.stringify(tc));
              continue; // Salta questo tool_call se la struttura base non è rispettata
            }

            let parsedArgs: Record<string, any>;
            if (typeof tc.args === 'string') {
              try {
                parsedArgs = JSON.parse(tc.args);
              } catch (parseError) {
                console.error(`Errore nel parsing degli argomenti JSON del tool_call (ID: ${tc.id}, Nome: ${tc.name}). Argomenti: '${tc.args}'. Errore:`, parseError);
                continue; // Salta questo tool_call se gli argomenti non sono JSON validi
              }
            } else if (typeof tc.args === 'object' && tc.args !== null) {
              parsedArgs = tc.args; // Gli argomenti sono già un oggetto
            } else {
              console.error(`Formato argomenti non valido per tool_call (ID: ${tc.id}, Nome: ${tc.name}). Argomenti:`, tc.args);
              continue; // Salta se gli argomenti non sono né stringa né oggetto
            }

            toolCallParts.push({
              type: 'tool-call',
              toolCallId: tc.id,
              toolName: tc.name, // Usa tc.name
              args: parsedArgs    // Usa gli argomenti parsati o diretti
            });
          } catch (e) { // Questo catch ora gestirà principalmente errori da JSON.parse
            const toolCallId = tc && typeof tc.id === 'string' ? tc.id : 'ID sconosciuto';
            const toolName = tc && typeof tc.name === 'string' ? tc.name : 'Nome strumento sconosciuto';
            console.error(`Errore imprevisto durante l'elaborazione del tool_call (ID: ${toolCallId}, Nome: ${toolName}). Dettagli:`, JSON.stringify(tc), `Errore:`, e);
          }
        }
        // Un messaggio assistente con tool_calls può avere anche contenuto testuale
        coreMessages.push({
          role: "assistant",
          content: msg.content ? [{ type: 'text', text: msg.content }, ...toolCallParts] : toolCallParts
        });
      } else {
        coreMessages.push({ role: "assistant", content: msg.content });
      }
    } else if (msg.type === "tool") {
      if (!msg.tool_call_id) {
        console.warn(`Messaggio Tool (type: ${msg.type}) senza tool_call_id: ${JSON.stringify(msg)}. Scartato.`);
        continue;
      }
      // Per i risultati degli strumenti, il content è un array di ToolResultPart
      const toolResultContent: ToolResultPart[] = [{
        type: 'tool-result',
        toolCallId: msg.tool_call_id,
        // Prova a ottenere il nome dello strumento dal tool_call originale se disponibile,
        // altrimenti usa un placeholder. Questo richiede che la cronologia dei messaggi
        // sia accessibile o che il backend fornisca il nome dello strumento nel messaggio di risultato.
        // Per ora, se msg.tool_calls è presente nel messaggio di tipo 'tool' (improbabile ma possibile), usalo.
        // Altrimenti, il backend dovrebbe idealmente includere il nome dello strumento nel risultato.
        // Visto che il backend invia il nome nel tool_call, e qui stiamo processando un tool_result,
        // il nome dello strumento per il risultato deve essere inferito o fornito esplicitamente.
        toolName: msg.tool_calls?.[0]?.name || "unknown_tool_name_in_result",
        result: msg.content, // Il risultato dello strumento
        // isError: false, // Opzionale, impostalo a true se lo strumento ha restituito un errore
      }];
      coreMessages.push({
        role: "tool",
        content: toolResultContent
      });
    } else {
      console.warn(`Ruolo/tipo non gestito '${msg.type}' in transformToCoreMessages. Messaggio scartato:`, msg);
    }
  }
  return coreMessages;
}

export async function POST(req: Request) {
  const { messages, system, tools } = await req.json();

  // Log dei messaggi ricevuti
  // console.log("ROUTE.TS: Messaggi ricevuti dal client UI:", JSON.stringify(messages, null, 2)); // Riduci verbosità

  try {
    // Controlla se non ci sono messaggi (prima interazione)
    if (!messages || messages.length === 0) {
      const welcomeMessage = {
        role: "assistant",
        content: "Ciao! Sono il tuo assistente virtuale. Posso aiutarti con prenotazioni, disponibilità e altro. Come posso aiutarti oggi?",
      };
      // Restituisci il messaggio di benvenuto
      return new Response(JSON.stringify(welcomeMessage), { // Restituisce un singolo oggetto, non un array
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    }

    // Invia i messaggi al backend tramite FastAPI
    const response = await fetch("http://127.0.0.1:8000/agent", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ messages }),
    });

    if (!response.ok) {
      throw new Error(`Errore dal backend: ${response.statusText}`);
    }

    console.log("ROUTE.TS: Risposta grezza dal backend FastAPI ricevuta (status OK).");
    // Specifica il tipo della risposta JSON con un cast esplicito
    const backendApiResponse = (await response.json()) as BackendApiResponse;
    console.log("ROUTE.TS: Messaggi ricevuti dal backend FastAPI:", JSON.stringify(backendApiResponse.messages, null, 2));

    // Normalizza solo i messaggi ricevuti dal backend FastAPI,
    // poiché questi dovrebbero rappresentare l'intera cronologia aggiornata.
    const normalizedBackendMessages = validateAndNormalizeMessages(backendApiResponse.messages);
    console.log("ROUTE.TS: Messaggi normalizzati (originati dal backend FastAPI):", JSON.stringify(normalizedBackendMessages, null, 2));

    // Trasforma i messaggi normalizzati nel formato CoreMessage per streamText
    const coreMessagesForStreamText = transformToCoreMessages(normalizedBackendMessages);

    console.log("ROUTE.TS: Messaggi finali inviati a streamText (OpenAI):", JSON.stringify(coreMessagesForStreamText, null, 2));

    // Controlla l'ultimo messaggio nella cronologia proveniente dal backend
    const lastMessageFromBackend = coreMessagesForStreamText[coreMessagesForStreamText.length - 1];

    // Se l'ultimo messaggio è dell'assistente e ha contenuto testuale (e non tool_calls in sospeso),
    // consideralo come la risposta finale del backend Python e invialo direttamente.
    // Assumiamo che se il content è una stringa, non ci sono tool_calls in sospeso.
    if (
      lastMessageFromBackend &&
      lastMessageFromBackend.role === 'assistant' &&
      typeof lastMessageFromBackend.content === 'string'
    ) {
      console.log("ROUTE.TS: L'ultimo messaggio del backend è una risposta testuale finale. Invio diretto all'UI.");
      
      const textContent = lastMessageFromBackend.content;
      const encoder = new TextEncoder();
      const stream = new ReadableStream({
        start(controller) {
          // Invia il contenuto testuale formattato per lo stream Vercel AI SDK
          // Il formato '0:"..."\n' è per i dati di testo.
          controller.enqueue(encoder.encode(`0:"${JSON.stringify(textContent).slice(1, -1)}"\n`));
          // Chiudi lo stream per indicare che il messaggio è completo
          controller.close();
        },
      });

      // Restituisci la risposta con l'header corretto per lo streaming di dati
      return new Response(stream, {
        headers: {
          'Content-Type': 'text/plain; charset=utf-8',
          'X-Experimental-Stream-Data': 'true'
        },
      });

    } else {
      console.log("ROUTE.TS: L'ultimo messaggio del backend non è una risposta testuale finale o contiene tool_calls. Chiamo streamText.");
      // Se l'ultimo messaggio non è una risposta testuale finale (es. è un tool_call),
      // lascia che streamText continui l'elaborazione.
      const result = streamText({
        model: openai("gpt-4o"),
        messages: coreMessagesForStreamText, // Usa la cronologia completa
        system: undefined, 
        tools: undefined, 
      });
      return result.toDataStreamResponse();
    }
  } catch (error) {
    // Log dell'errore
    console.error("Errore durante l'esecuzione:", error);

    // Restituisci un messaggio di errore al client
    const errorMessage = {
      role: "assistant",
      content: "Si è verificato un errore interno. Riprova più tardi o contatta il supporto.",
    };
    return new Response(JSON.stringify(errorMessage), { // Restituisce un singolo oggetto
      status: 500,
      headers: { 'Content-Type': 'application/json' },
    });
  }
}