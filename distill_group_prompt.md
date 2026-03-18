# GROUP SYNTHESIS PROMPT

You are synthesizing consecutive sections of a book into one unified distillation.

The input contains multiple individually distilled analyses, each from a different part of the same chapter/section group. These distillations already extracted receptors, operations, immune responses, and seed principles from their respective chunks.

## YOUR TASK

MERGE into ONE coherent distillation that is greater than the sum of its parts.

### Rules:
- **Deduplicate ruthlessly**: If multiple chunks identified the same receptor or operation, merge them into the strongest version. Don't list the same idea twice.
- **Fill gaps**: If chunk A has an operation that chunk B is missing, and chunk A provides the context for it, include it in the merged version.
- **Connect the dots**: Look for relationships between ideas from different chunks. The whole point of group synthesis is to see connections that individual chunks couldn't reveal.
- **Elevate, don't repeat**: The output should be MORE refined than any single input, not just a concatenation.
- **Do NOT add new ideas**: Only work with what's in the inputs. If something seems missing, note it as a gap rather than inventing content.
- **Maintain structure**: Use the same format (Core Thesis, Receptors, Operations, Immune Responses, Generator, Cold Storage).

### Output Format:

```
CORE THESIS: [The unified thesis across all chunks in this group]

RECEPTORS ENABLED (The "What"):
[Merged and deduplicated. Keep the best version of each concept.]

OPERATIONS ENABLED (The "How"):
[Merged heuristics. If two chunks have similar triggers/actions, combine them.]

IMMUNE RESPONSES (The "Shield"):
[Merged anti-patterns. Focus on the ones most relevant across all chunks.]

THE GENERATOR (Atomic Logic):
[The seed principle that captures ALL chunks in this group.]

THE "COLD STORAGE" SYNTHESIS:
[One paragraph that captures the essence of this entire group.]
```

Output clean markdown only. Be ruthless about quality.
