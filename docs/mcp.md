# Rigorloom as an MCP server

`rigorloom mcp` serves the document tools to an agent over stdio (MCP
2025-06-18). They are the same tools the `rigorloom` command runs, from the
same registry, so an agent and a person at the terminal get the same results.

## Add it to a client

Any MCP client that starts a stdio server can run it. Name the folders the
agent may read and write with `--allow`, once per folder:

```sh
claude mcp add rigorloom -- rigorloom mcp --allow "$HOME/문서"
```

A client configured with JSON takes the same command and arguments:

```json
{
  "mcpServers": {
    "rigorloom": {
      "command": "rigorloom",
      "args": ["mcp", "--allow", "D:\\문서"]
    }
  }
}
```

## Tools

| tool | what it does |
|---|---|
| `open` | outline, fill-in places, draft status and addresses |
| `read` | exact text at an address (`p12`, `t3/r2/c1`, `place:<id>`) |
| `find` | where a phrase occurs, with addresses |
| `edit` | stage changes in the draft; the person's file is untouched |
| `fill` | fill form places; signature, seal and approval-date places are left for the person |
| `new` | a new document from markdown, as `draft:<id>` |
| `preview` | page images of the draft |
| `check` | style, layout, font and changed-number checks |
| `save` | write the draft to a file |
| `changes` | drafts and save history |
| `guide` | writing guides for official letters, reports and forms |

## Folders

The agent works only inside its roots: the folders the client names
(`roots/list`) plus every `--allow` folder. A client that never names a folder
gets the server's working folder instead, unless that is the home folder or a
filesystem root; with no folder at all, every tool answers `no_roots` with the
`--allow` line to add. When the client announces a change, its old folders stop
counting at once. A folder that is replaced by a link, or by another folder of
the same name, stops counting too. A `draft:<id>` of a file is confined like
the file.

Pictures that markdown names are checked against the same roots, in the places
the converter reads a picture: in `new`, a line that is only `![설명](경로)`
or a `[그림 1] 설명 (그림.png)` line; in a `.md` file saved to another format,
also `![설명](경로)` anywhere outside code. Each must be an existing file inside
the roots. The converter reads a private copy of it, so a folder name with
brackets in it works and the person's path does not end up in the document.
Everything else, a link or a file name in brackets, stays text exactly as
written, and `edit`'s `insert_after` adds text only. A line written as a
picture that the converter would take as text (brackets in the file name, two
pictures on one line, `[그림 1] 설명 (그림.PNG)`) is refused with
`invalid_params` rather than left in the document as markdown. If the built
document still holds a picture that was not checked, the call stops with
`invalid_params` and nothing is kept.

## Saving over a file

`save` to a new path creates the file. Replacing a file the draft did not
create asks the person through the client (MCP elicitation), with the same
facts the terminal prompt shows: the target, changed pages, change sets nobody
has reviewed, what a conversion loses, substituted fonts, and how to undo. A
client that cannot ask gets `needs_person` with the command a person can run.

- A "no" holds for those bytes at that file, in every session; the agent is
  told not to ask again.
- Cancelling the call (`notifications/cancelled`) withdraws the question and
  writes nothing. So does a malformed answer, or no answer in ten minutes.
- If the client takes the folder away while the person decides, nothing is
  written.
- The replaced bytes go to the save history; `rigorloom undo FILE` puts them
  back.

## Results and refusals

Each result is a short text block plus the full result as
`structuredContent`, which matches the tool's `outputSchema`. A refusal is an
`isError` result whose `structuredContent.error` carries a stable `code`, a
Korean `message` and `hint`, and `retryable`. `preview` sends page images,
dropping pages from the end when the message would pass the size limit, and
says which ones it left out.
