"""curator_inference: the one road a curator's model call takes.

The provider table, the sovereign-inference guard, the config precedence, the key
lookup and the HTTP chat helpers, moved out of bin/curator-run so a second caller can
judge through the same law without lifting source by AST or importing a script that
evaluates its own guard at module level. curator-run keeps its old names as aliases.

Nothing here reads os.environ: config_from_env takes the env it is given, and chat
reads local_only from that config, so a caller decides what the call sees. chat runs
the guard itself on every call and refuses a config that fails it.
"""
import json
import os
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request

# The hosted providers a hubless archive's owner may choose (rule 5, amended
# 2026-10-18): exactly one at a time, under the owner's own account, pinned to
# that provider's own API host. "backend" is the wire shape; only Anthropic
# speaks its Messages API, the rest speak the OpenAI chat shape. Default models
# are starting points; CURATOR_MODEL overrides. Muse's endpoint is empty on
# purpose: no canonical public inference host exists yet, so CURATOR_ENDPOINT
# must name its https API endpoint or the guard refuses.
PROVIDERS = {
    "anthropic": {"name": "Anthropic", "backend": "anthropic",
                  "endpoint": "https://api.anthropic.com/v1/messages",
                  "host": "api.anthropic.com", "model": "claude-opus-5-5"},
    "openai": {"name": "OpenAI", "backend": "openai",
               "endpoint": "https://api.openai.com/v1/chat/completions",
               "host": "api.openai.com", "model": "gpt-5.6"},
    "gemini": {"name": "Google Gemini", "backend": "openai",
               "endpoint": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
               "host": "generativelanguage.googleapis.com", "model": "gemini-2.5-pro"},
    "grok": {"name": "xAI Grok", "backend": "openai",
             "endpoint": "https://api.x.ai/v1/chat/completions",
             "host": "api.x.ai", "model": "grok-4.7"},
    "muse": {"name": "Muse", "backend": "openai",
             "endpoint": "", "host": "", "model": "muse-wonder-full-1.0"},
}


def inference_violations(endpoint, model, screen_model, allow_remote,
                         local_hosts=("localhost", "127.0.0.1", "::1", "0.0.0.0"),
                         backend="openai", local_only=False, provider=""):
    """The law: every model that reads vault-derived content runs on inference the
    owner controls, with no cloud primary and no cloud fallback in the curation
    path. Until 2026-08-28 that was enforced only by the DEFAULTS being local, so a
    one-token typo in CURATOR_MODEL (a hosted ':cloud' tag, say) would egress vault
    content and still look like a clean run.

    Two independent ways to leave the box, so two checks: a non-loopback ENDPOINT,
    and a model id carrying a hosted-inference marker even on a local endpoint
    (Ollama's ':cloud' tag proxies through the vendor's servers, and the request
    still goes to localhost:11434).

    Pure and injectable so --self-test covers it with no env and no network.
    Returns a list of violation strings; empty means clean. `allow_remote` is the
    explicit owner opt-out the law allows, and is reported by the caller so an
    opted-out run is never silent.

    A chosen provider is the standard's second lawful shape (rule 5, 2026-10-13;
    widened 2026-10-18 from Anthropic alone to the PROVIDERS table): a hosted
    provider the owner chose under their own account, judging and drafting only,
    never holding the gate. It is exactly one provider at a time at exactly its
    own API host, and an archive marked local-only (local_only) refuses every
    hosted provider whatever else is set. Muse's host is not canonical yet, so
    its pin is the shape itself: an https, non-loopback endpoint the owner named."""
    if backend not in ("openai", "anthropic"):
        return [f"CURATOR_BACKEND is not a known backend: {backend}"]
    if not provider and backend == "anthropic":
        provider = "anthropic"
    if provider:
        p = PROVIDERS.get(provider)
        if p is None:
            return [f"CURATOR_PROVIDER is not a known provider: {provider}"]
        if local_only:
            return [f"CURATOR_PROVIDER={provider} on an archive marked local-only (CURATOR_LOCAL_ONLY=1)"]
        if backend != p["backend"]:
            return [f"CURATOR_BACKEND={backend} does not speak the {provider} provider's API shape"]
        u = urllib.parse.urlparse(endpoint)
        host = (u.hostname or "").lower()
        if u.scheme != "https" or not host or host in local_hosts:
            return [f"the {provider} provider only talks to its own https API host, not {endpoint}"]
        if p["host"] and host != p["host"]:
            return [f"the {provider} provider only talks to https://{p['host']}, not {endpoint}"]
        return []
    if allow_remote:
        return []
    out = []
    host = urllib.parse.urlparse(endpoint).hostname or ""
    if host.lower() not in local_hosts and not host.lower().endswith(".local"):
        out.append(f"endpoint is not local: {host or endpoint}")
    for label, m in (("CURATOR_MODEL", model), ("CURATOR_SCREEN_MODEL", screen_model)):
        if m and m.strip().lower().endswith(":cloud"):
            out.append(f"{label} is a hosted model: {m}")
    return out


_TRUE = ("1", "on", "true", "yes")
LOCAL_ENDPOINT = "http://localhost:11434/v1/chat/completions"


def config_from_env(env):
    """The curator's inference config from an env mapping. Local by default, the law:
    machine writers to knowledge/ run on owner-controlled compute, and a hosted
    provider is an explicit owner choice, never a default."""
    provider = (env.get("CURATOR_PROVIDER") or "").strip().lower()
    p = PROVIDERS.get(provider) or {}
    backend = (env.get("CURATOR_BACKEND") or p.get("backend") or "openai").strip().lower()
    # A bare CURATOR_BACKEND=anthropic (the pre-provider single-Mac wiring) is the
    # anthropic provider by another name.
    if not provider and backend == "anthropic":
        provider, p = "anthropic", PROVIDERS["anthropic"]
    endpoint = env.get("CURATOR_ENDPOINT") or p.get("endpoint") or (
        PROVIDERS["anthropic"]["endpoint"] if backend == "anthropic" else LOCAL_ENDPOINT)
    model = env.get("CURATOR_MODEL") or p.get("model") or (
        "claude-opus-5-5" if backend == "anthropic" else "qwen3.8:27b")
    return {
        "provider": provider,
        "backend": backend,
        "endpoint": endpoint,
        "model": model,
        "screen_model": env.get("CURATOR_SCREEN_MODEL", model),
        "local_only": env.get("CURATOR_LOCAL_ONLY") == "1",
        "allow_remote": env.get("CURATOR_ALLOW_REMOTE", "").strip().lower() in _TRUE,
        "keychain_service": f"sovereign-curator-{provider}" if provider else "",
        "keyfile": env.get("CURATOR_KEYFILE", ""),
        # The judge thinks: empty sends no reasoning_effort, so the model's default
        # applies (owner reverted "none" on 2026-09-23 after it lost live recall).
        "reasoning_effort": env.get("CURATOR_REASONING_EFFORT", ""),
        "anthropic_effort": env.get("CURATOR_EFFORT") or "medium",
    }


def violations(cfg):
    """inference_violations over a config_from_env result; empty means clean."""
    return inference_violations(cfg["endpoint"], cfg["model"], cfg["screen_model"], cfg["allow_remote"],
                                backend=cfg["backend"], local_only=cfg["local_only"],
                                provider=cfg["provider"])


def load_key(cfg, env):
    """The API key: the keyfile, then CURATOR_KEY, then, when a provider is chosen, the
    owner's own key for it saved by the app into the login Keychain (never on argv or
    disk). Empty when none is found; the caller decides whether that is fatal."""
    keyfile = cfg.get("keyfile") or ""
    if keyfile and os.path.exists(keyfile):
        with open(keyfile, encoding="utf-8") as fh:
            key = fh.read().strip()
    else:
        key = env.get("CURATOR_KEY", "")
    if cfg.get("provider") and not key:
        try:
            key = subprocess.run(["/usr/bin/security", "find-generic-password", "-s", cfg["keychain_service"], "-w"],
                                 capture_output=True, text=True, timeout=20).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            key = ""
    return key


def chosen_provider(state_dir):
    """The hosted provider a hubless archive's owner chose (`sov curator provider`),
    from <state_dir>/curator-provider.json. Anthropic when unset or unknown."""
    try:
        with open(os.path.join(state_dir, "curator-provider.json"), encoding="utf-8") as fh:
            p = json.load(fh).get("provider")
    except Exception:
        p = None
    return p if p in PROVIDERS else "anthropic"


def _post_json(req, timeout, local_only=False):
    """One retry on a timed-out model call. A single timeout otherwise costs the
    document until the next run; transient queue pressure should not do that."""
    open_request = urllib.request.urlopen
    if local_only:
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                raise ValueError("Local Hub inference redirects are refused.")
        open_request = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect()).open
    try:
        return json.load(open_request(req, timeout=timeout))
    except urllib.error.HTTPError as exc:
        # Keep the server's own explanation ("`temperature` is deprecated for this
        # model"): a bare "400 Bad Request" in the judgments log says nothing. The body
        # is the provider's error object; the request's key is never in it.
        try:
            detail = exc.read(400).decode("utf-8", "replace").strip()
        except Exception:
            detail = ""
        raise RuntimeError(f"HTTP {exc.code}: {detail or exc.reason}") from None
    except Exception as exc:
        if "timed out" not in str(exc).lower():
            raise
        time.sleep(30)
        return json.load(open_request(req, timeout=timeout))


def _chat_body(model, temperature, messages, reasoning_effort=""):
    """The request body of every model call, so the judge, the update merge and the
    screen cannot drift apart on how they ask."""
    body = {"model": model, "temperature": temperature, "stream": False,
            "response_format": {"type": "json_object"}, "messages": messages}
    if reasoning_effort:
        body["reasoning_effort"] = reasoning_effort
    return json.dumps(body).encode()


def _anthropic_body(model, messages, effort="medium"):
    """The same request on the Messages API. Current Claude models refuse sampling
    parameters (temperature is a 400) and always think, so there is no temperature
    and no thinking switch: effort sets the depth. max_tokens leaves room for the
    thinking as well as the card. No JSON mode: every prompt already asks for one JSON
    object and the callers extract it. A refused request is retried on Anthropic's
    fallback model rather than failing (server-side fallback, routed by category)."""
    system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
    rest = [{"role": m["role"], "content": m["content"]} for m in messages if m["role"] != "system"]
    body = {"model": model, "max_tokens": 16000, "output_config": {"effort": effort},
            "fallbacks": "default", "messages": rest}
    if system:
        body["system"] = system
    return json.dumps(body).encode()


def chat(cfg, key, model, temperature, messages, timeout):
    """Every model call goes through here, so the backends cannot drift apart. Returns
    the reply text. The guard runs here on every call, before any request is built,
    so a caller that skipped violations(cfg), or edited cfg after checking it, is
    refused rather than sent."""
    found = violations(cfg)
    if found:
        raise RuntimeError(f"REFUSING - sovereign-inference law: {found[0]}")
    local_only = bool(cfg.get("local_only"))
    if cfg["backend"] == "anthropic":
        req = urllib.request.Request(cfg["endpoint"], _anthropic_body(model, messages, cfg.get("anthropic_effort") or "medium"),
                                     {"x-api-key": key, "anthropic-version": "2023-06-01",
                                      "anthropic-beta": "server-side-fallback-2026-07-01",
                                      "Content-Type": "application/json"})
        out = _post_json(req, timeout, local_only)
        # Read the stop reason before the content: a refusal or a cut-off reply is an
        # error for this item (recorded, retried next run), never an empty verdict.
        stop = out.get("stop_reason")
        if stop in ("refusal", "max_tokens"):
            raise ValueError(f"Claude stopped with {stop}" + (
                f" ({(out.get('stop_details') or {}).get('category')})" if stop == "refusal" else ""))
        return "".join(b.get("text", "") for b in out.get("content", []) if b.get("type") == "text")
    req = urllib.request.Request(cfg["endpoint"], _chat_body(model, temperature, messages, cfg.get("reasoning_effort") or ""),
                                 {"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    return _post_json(req, timeout, local_only)["choices"][0]["message"]["content"]
