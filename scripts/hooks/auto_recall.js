#!/usr/bin/env node
/**
 * UserPromptSubmit hook for the two-agent trajectory memory flow.
 *
 * The hook only reads config and injects additionalContext. It never
 * performs retrieval or planning directly.
 */

const fs = require("fs");
const os = require("os");
const path = require("path");

const DEFAULT_CONFIG_PATH = "~/.claude/learn-once/config.json";
const ADDITIONAL_CONTEXT =
  "Auto recall is enabled for this turn. Before normal execution, invoke the `trajectory-memory-suggester` subagent with the user's current prompt and the latest planning state. Ask it: based on your past trajectory experiences, what recommendations do you have for executing the following task: '<当前具体任务描述>'. Follow the returned planning if provided.";

function expandHome(value, homeDir = os.homedir()) {
  if (!value || !value.startsWith("~")) {
    return value;
  }
  return path.join(homeDir, value.slice(2));
}

function safeReadJson(filePath) {
  try {
    if (!fs.existsSync(filePath)) {
      return null;
    }
    return JSON.parse(fs.readFileSync(filePath, "utf-8"));
  } catch (_error) {
    return null;
  }
}

function loadConfig(homeDir = os.homedir()) {
  const configPath = expandHome(DEFAULT_CONFIG_PATH, homeDir);
  return safeReadJson(configPath) || {};
}

function extractPrompt(payload, argv = process.argv.slice(2)) {
  const promptFlagIndex = argv.indexOf("--prompt");
  if (promptFlagIndex >= 0 && argv[promptFlagIndex + 1]) {
    return String(argv[promptFlagIndex + 1]).trim();
  }

  const candidates = [
    payload && payload.prompt,
    payload && payload.userPrompt,
    payload && payload.message,
    payload && payload.input && payload.input.prompt,
    payload && payload.params && payload.params.prompt,
  ];

  for (const candidate of candidates) {
    if (candidate && String(candidate).trim()) {
      return String(candidate).trim();
    }
  }

  return "";
}

function buildHookOutput() {
  return {
    hookSpecificOutput: {
      hookEventName: "UserPromptSubmit",
      additionalContext: ADDITIONAL_CONTEXT,
    },
  };
}

function readStdin() {
  return new Promise((resolve) => {
    let content = "";
    process.stdin.setEncoding("utf8");
    process.stdin.on("data", (chunk) => {
      content += chunk;
    });
    process.stdin.on("end", () => {
      resolve(content.trim());
    });
    process.stdin.on("error", () => {
      resolve("");
    });

    if (process.stdin.isTTY) {
      resolve("");
    }
  });
}

async function main() {
  const rawInput = await readStdin();
  let payload = {};
  if (rawInput) {
    try {
      payload = JSON.parse(rawInput);
    } catch (_error) {
      payload = {};
    }
  }

  const config = loadConfig();
  if (!config.enable_auto_recall) {
    return;
  }

  const prompt = extractPrompt(payload);
  if (!prompt) {
    return;
  }

  process.stdout.write(JSON.stringify(buildHookOutput()));
}

if (require.main === module) {
  main().catch(() => {
    process.exitCode = 0;
  });
}

module.exports = {
  ADDITIONAL_CONTEXT,
  buildHookOutput,
  expandHome,
  extractPrompt,
  loadConfig,
  safeReadJson,
};
