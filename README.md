# LLM Wiki Workflow - Skills

file-ingest + tag-curation 打包為可安裝 Skill。

## 安裝方式

```bash
clawhub install file-ingest --dir skills --workdir ~/.openclaw/workspace
```

或從 GitHub 直接 clone：
```bash
git clone https://github.com/openclawGit200/LLM_WIKI_workflow.git ~/.openclaw/workspace/skills/llm-wiki-workflow
```

## 內含 Skills

### file-ingest v1.0

將各種格式檔案轉換為乾淨 Markdown，存入 Obsidian Vault。

**支援格式**：docx / pdf / pptx / xlsx / html / txt / md

**依賴工具**：
-  — docx/html/pptx/xlsx → Markdown
- （poppler）— PDF → txt
- textutil: [command_option] [other_options] file...
Command options are (-help is the default):
 -help          show this message and exit
 -info          display information about each file
 -convert fmt   convert each input file to format (txt, rtf, rtfd,
                html, doc, docx, odt, wordml, or webarchive)
 -cat fmt       concatenate input files into one output file
There are some additional optional arguments:
 -extension ext alternate extension for all output files
 -output path   alternate file name for first output file
 -stdin         read from stdin instead of files
 -stdout        send first output file to stdout
 -encoding IANA_name|NSStringEncoding
                encoding used for plain text or html output files
                (default encoding is UTF-8)
 -inputencoding IANA_name|NSStringEncoding
                encoding used to interpret plain text input files
                (by default encoding will be detected from BOM)
 -format fmt    force input files to be interpreted in this format
 -font font     specify font used for converting plain to rich text
 -fontsize size specify font size for converting plain to rich text
 --             specifies that all further arguments are file names

 -noload        do not load subsidiary resources for html files
 -nostore       do not write out subsidiary resources for html files
 -baseurl url   base URL for subsidiary resources in html files
 -timeout t     time in seconds to wait for html resources to load
 -textsizemultiplier x
                factor to apply to font sizes in html files
 -excludedelements "(tag1, tag2, ...)"
                html elements to exclude from html output files
 -prefixspaces n
                number of spaces to indent nested html output

 -strip         do not copy metadata attributes to output files
 -title val     title metadata attribute for output files
 -author val    author metadata attribute for output files
 -subject val   subject metadata attribute for output files
 -keywords "(val1, val2, ...)"
                keywords metadata attribute for output files
 -comment val   comment metadata attribute for output files
 -editor val    last editor metadata attribute for output files
 -company val   company metadata attribute for output files
 -creationtime yyyy-mm-ddThh:mm:ssZ
                creation time metadata attribute for output files
 -modificationtime yyyy-mm-ddThh:mm:ssZ
                modification time metadata attribute for output files（macOS）— rtf/doc → docx
-  /  — Python 庫

**使用**：
```bash
python3 scripts/convert.py "/path/to/file.docx" [--vault-path /path/to/vault]
```

**輸出**：Obsidian Vault 

詳見 SKILL.md

## 檔案結構


