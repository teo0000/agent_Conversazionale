// C:\Users\A58\Desktop\Progetto Tirocinio\_\Frontend\lib\did.ts

// Definiamo i tipi per la risposta dell'API di D-ID per maggiore chiarezza
interface DidTalk {
    id: string;
    status: "created" | "started" | "done" | "error" | "rejected";
    result_url?: string;
    // Aggiungiamo altri campi in caso di errore per un debug migliore
    error?: string;
    description?: string;
}

// Funzione per attendere un certo numero di millisecondi
const sleep = (ms: number) => new Promise(resolve => setTimeout(resolve, ms));

/**
 * Genera un video da D-ID a partire da un testo.
 * @param text Il testo da convertire in video.
 * @returns L'URL del video generato o null in caso di errore.
 */
export async function generateDIdVideo(text: string): Promise<string | null> {
    const apiKey = process.env.D_ID_API_KEY;
    const avatarUrl = process.env.NEXT_PUBLIC_AVATAR_IMAGE_URL;

    if (!apiKey || !avatarUrl) {
        console.error("D-ID API key or Avatar URL are not configured in .env.local");
        return null;
    }

    try {
        // --- 1. Creare il "talk" (la richiesta di generazione video) ---
        const createResponse = await fetch("https://api.d-id.com/talks", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                // La chiave API va codificata in Base64 e aggiunta al suffisso ":"
                // Questo è specifico per l'autenticazione Basic di D-ID
                Authorization: `Basic ${Buffer.from(apiKey + ":").toString("base64")}`,
            },
            body: JSON.stringify({
                script: {
                    type: "text",
                    input: text,
                },
                source_url: avatarUrl,
                config: {
                    stitch: true, // Assicura che l'output sia un video completo
                },
            }),
        });

        if (!createResponse.ok) {
            const errorData = await createResponse.json();
            console.error("D-ID create talk error:", errorData);
            return null;
        }

        const createResult: DidTalk = await createResponse.json();
        const talkId = createResult.id;

        // --- 2. Polling per ottenere il risultato del video ---
        // La generazione non è istantanea, quindi dobbiamo chiedere a D-ID lo stato
        // del nostro video a intervalli regolari finché non è pronto.
        let attempts = 0;
        const maxAttempts = 60; // Attesa massima di circa 60 secondi

        while (attempts < maxAttempts) {
            await sleep(1000); // Attendi 1 secondo tra un tentativo e l'altro

            const getResponse = await fetch(`https://api.d-id.com/talks/${talkId}`, {
                method: "GET",
                headers: {
                    Authorization: `Basic ${Buffer.from(apiKey + ":").toString("base64")}`,
                },
            });

            const talk: DidTalk = await getResponse.json();

            if (talk.status === "done") {
                console.log(`Video generated successfully: ${talk.result_url}`);
                return talk.result_url ?? null;
            } else if (talk.status === "error" || talk.status === "rejected") {
                console.error("D-ID video generation failed:", talk.error, talk.description);
                return null;
            }

            attempts++;
        }

        console.error("D-ID video generation timed out after 60 seconds.");
        return null;

    } catch (error) {
        console.error("An unexpected error occurred while generating D-ID video:", error);
        return null;
    }
}
