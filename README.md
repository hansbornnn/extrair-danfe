# Extrator de DANFE / NF-e

Programa Python que lê PDFs de DANFE e extrai o **número da nota fiscal** e a **quantidade** do quadro de transporte. Roda como app web (Streamlit) ou direto pelo terminal.

---

## O que ele faz

- Importa um ou vários PDFs de DANFE
- Localiza o número da NF-e (usando coordenadas do PDF e fallback por texto)
- Pega a quantidade do bloco TRANSPORTADOR/VOLUMES TRANSPORTADOS — sem confundir com a quantidade dos produtos
- Gera uma tabela exportável em `.xlsx`

---

## Instalação

pip install pymupdf pandas openpyxl streamlit

---

## Como usar

### Interface web (Streamlit)
Abre no navegador, você arrasta os PDFs e baixa o Excel no final.
Imprime a tabela no terminal e salva `resultado_danfe.xlsx` na pasta atual.
---

## Saída

| Arquivo | Numero_NF | Quantidade | Pagina | Observacao |
|---------|-----------|------------|--------|------------|
| nf_001.pdf | 123456 | 10 | 1 | OK |
| nf_002.pdf | 789012 | — | 1 | Quantidade não localizada no quadro de transporte |

---

## Observações

- PDFs com múltiplas páginas por nota (2/2, 3/3...) são tratados corretamente — a NF só aparece uma vez na saída.
- A extração por coordenadas funciona bem para DANFEs no layout padrão SEFAZ. Se o seu PDF vier de algum ERP com layout bem diferente, o fallback por texto tenta cobrir.
- Não depende de OCR — funciona apenas com PDFs que têm texto embutido (a grande maioria dos DANFEs gerados digitalmente).

Dependências

PyMuPDF
pandas
openpyxl
streamlit
