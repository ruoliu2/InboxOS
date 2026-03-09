type ClassInput =
  | string
  | false
  | null
  | undefined
  | ClassInput[]
  | Record<string, boolean | null | undefined>;

function flatten(input: ClassInput, output: string[]): void {
  if (!input) {
    return;
  }

  if (typeof input === "string") {
    output.push(input);
    return;
  }

  if (Array.isArray(input)) {
    for (const value of input) {
      flatten(value, output);
    }
    return;
  }

  for (const [key, enabled] of Object.entries(input)) {
    if (enabled) {
      output.push(key);
    }
  }
}

export function cn(...inputs: ClassInput[]): string {
  const output: string[] = [];
  for (const input of inputs) {
    flatten(input, output);
  }
  return output.join(" ");
}
