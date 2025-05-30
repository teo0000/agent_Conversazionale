export const removeDuplicatePhrases = (text: string): string => {
    const words = text.trim().split(/\s+/);
    if (words.length < 4) return text;
    const n = words.length;
    for (let len = Math.floor(n / 2); len >= 2; len--) {
        for (let start = 0; start <= n - 2 * len; start++) {
            const seq1 = words.slice(start, start + len).join(" ");
            const seq2 = words.slice(start + len, start + 2 * len).join(" ");
            if (seq1 === seq2) {
                return words.slice(0, start + len).concat(words.slice(start + 2 * len)).join(" ");
            }
        }
    }
    return text;
};

export const cleanTextForProcessing = (text: string): string => {
    let cleaned = text;
    cleaned = removeDuplicatePhrases(cleaned);
    // Altri step di pulizia generali qui se necessario
    return cleaned.trim();
};

export const cleanTextForTTS = (text: string): string => {
    let cleaned = text.replace(/\*/g, "");
    cleaned = cleaned.replace(/\[\d+\]|\(\d+\)/g, "");
    cleaned = cleaned.replace(/(^|\n)\s*\d+[\.|\)]\s*/g, "$1");
    cleaned = cleaned.replace(/\s{2,}/g, " ");
    return cleaned.trim();
};
