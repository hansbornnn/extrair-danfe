"""
Extrator Online de DANFE/NF-e
Função principal: importar PDFs e extrair o Nº da NF-e e a QUANTIDADE
principal da área TRANSPORTADOR/VOLUMES TRANSPORTADOS.

Como usar online/local:
1) pip install -r requirements.txt
2) streamlit run danfe_extractor.py
3) Abra o link que aparecer e importe os PDFs.
"""

from __future__ import annotations

import io
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

import fitz  # PyMuPDF
import pandas as pd


@dataclass
class ResultadoDanfe:
    arquivo: str
    numero_nf: str | None
    quantidade: str | None
    pagina: int | None
    observacao: str = ""


# -----------------------------
# Extração por texto do PDF
# -----------------------------

def limpar_numero(texto: str | None) -> str | None:
    if not texto:
        return None
    numeros = re.sub(r"\D", "", str(texto))
    return numeros or None


def achar_numero_nf(texto: str) -> str | None:
    """Procura o número da NF-e no texto da página."""
    padroes = [
        r"NF-?e\s*N[ºo°\.]*\s*(\d{5,12})",
        r"N[ºo°\.]\s*(\d{5,12})\s*S[ÉE]RIE",
        r"(?:DANF-?e|DANFE).*?N[ºo°\.]*\s*(\d{5,12})",
    ]
    for padrao in padroes:
        m = re.search(padrao, texto, flags=re.IGNORECASE | re.DOTALL)
        if m:
            return limpar_numero(m.group(1))

    # Fallback: números grandes perto de "SÉRIE" ou no topo do DANFE
    linhas = [l.strip() for l in texto.splitlines() if l.strip()]
    for i, linha in enumerate(linhas):
        bloco = " ".join(linhas[max(0, i - 2): i + 3])
        if re.search(r"NF-?e|S[ÉE]RIE", bloco, re.IGNORECASE):
            nums = re.findall(r"\b\d{5,12}\b", bloco)
            if nums:
                return nums[0]
    return None



def achar_numero_nf_por_posicao(page: fitz.Page) -> str | None:
    """Pega o número da NF-e no quadro superior direito usando coordenadas."""
    words = page.get_text("words")
    candidatos = []
    for w in words:
        x0, y0, x1, y1, txt = w[:5]
        if 480 <= x0 <= 590 and 15 <= y0 <= 75 and re.fullmatch(r"\d{5,12}", txt.strip()):
            candidatos.append((y0, x0, txt.strip()))
    if candidatos:
        candidatos.sort()
        return candidatos[0][2]
    return None

def achar_quantidade_por_posicao(page: fitz.Page) -> str | None:
    """
    Extrai a QUANTIDADE do quadro TRANSPORTADOR/VOLUMES usando as posições
    das palavras no PDF. Isso evita pegar a quantidade da tabela de produtos.
    """
    words = page.get_text("words")
    if not words:
        return None

    # Procurar a palavra QUANTIDADE do quadro de transporte.
    candidatos = []
    for w in words:
        x0, y0, x1, y1, text = w[:5]
        if text.upper().strip() in {"QUANTIDADE", "QTD"}:
            # Na maioria dos DANFEs, esse campo fica antes de "DADOS DO PRODUTO".
            candidatos.append((x0, y0, x1, y1, text))

    for x0, y0, x1, y1, _ in candidatos:
        # Valor costuma ficar logo abaixo da etiqueta QUANTIDADE, dentro da mesma caixa.
        abaixo = []
        for ww in words:
            wx0, wy0, wx1, wy1, txt = ww[:5]
            if y1 <= wy0 <= y1 + 25 and x0 - 10 <= wx0 <= x0 + 75:
                if re.fullmatch(r"\d{1,9}", txt.strip()):
                    abaixo.append((wy0, wx0, txt.strip()))
        if abaixo:
            abaixo.sort()
            return abaixo[0][2]

    return None


def achar_quantidade_por_texto(texto: str) -> str | None:
    """Fallback por texto corrido, tentando limitar entre TRANSPORTADOR e DADOS DO PRODUTO."""
    t = re.sub(r"[ \t]+", " ", texto)
    m_secao = re.search(
        r"TRANSPORTADOR.*?QUANTIDADE.*?(?:DADOS DO PRODUTO|DADOS DOS PRODUTOS|C[ÓO]DIGO)",
        t,
        flags=re.IGNORECASE | re.DOTALL,
    )
    secao = m_secao.group(0) if m_secao else t

    # Após a palavra QUANTIDADE, pega números pequenos antes de DADOS DO PRODUTO.
    m = re.search(r"QUANTIDADE\s+.*?(\b\d{1,7}\b)", secao, flags=re.IGNORECASE | re.DOTALL)
    if m:
        return m.group(1)
    return None


def extrair_danfes_do_pdf(pdf_bytes: bytes, nome_arquivo: str) -> list[ResultadoDanfe]:
    """Retorna uma linha por NF-e encontrada dentro do PDF."""
    resultados: list[ResultadoDanfe] = []
    vistos: set[str] = set()

    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        for idx, page in enumerate(doc, start=1):
            texto = page.get_text("text") or ""
            numero_nf = achar_numero_nf_por_posicao(page) or achar_numero_nf(texto)

            if not numero_nf:
                continue

            # Evita repetir a mesma NF nas páginas 2/2, 3/3 etc.
            if numero_nf in vistos:
                continue

            quantidade = achar_quantidade_por_posicao(page) or achar_quantidade_por_texto(texto)

            # Se a página não tiver QUANTIDADE, procura nas próximas páginas da mesma NF.
            if not quantidade:
                for prox in range(idx, min(idx + 2, len(doc))):
                    p2 = doc[prox]
                    texto2 = p2.get_text("text") or ""
                    if (achar_numero_nf_por_posicao(p2) or achar_numero_nf(texto2)) == numero_nf:
                        quantidade = achar_quantidade_por_posicao(p2) or achar_quantidade_por_texto(texto2)
                        if quantidade:
                            break

            vistos.add(numero_nf)
            resultados.append(
                ResultadoDanfe(
                    arquivo=nome_arquivo,
                    numero_nf=numero_nf,
                    quantidade=quantidade,
                    pagina=idx,
                    observacao="OK" if quantidade else "Quantidade não localizada no quadro de transporte",
                )
            )

    if not resultados:
        resultados.append(
            ResultadoDanfe(
                arquivo=nome_arquivo,
                numero_nf=None,
                quantidade=None,
                pagina=None,
                observacao="Nenhuma NF-e encontrada no PDF",
            )
        )

    return resultados


# -----------------------------
# Exportação Excel
# -----------------------------

def gerar_excel(df: pd.DataFrame) -> bytes:
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="DANFE")
        ws = writer.book["DANFE"]
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions
        for col in ws.columns:
            maior = max(len(str(cell.value)) if cell.value is not None else 0 for cell in col)
            ws.column_dimensions[col[0].column_letter].width = min(max(maior + 2, 12), 45)
    buffer.seek(0)
    return buffer.getvalue()


# -----------------------------
# Interface Online Streamlit
# -----------------------------

def app_streamlit() -> None:
    import streamlit as st
    st.set_page_config(page_title="Extrator DANFE", page_icon="📄", layout="centered")

    st.title("📄 Extrator Online de DANFE / NF-e")
    st.write("Importe PDFs e extraia automaticamente o **Nº da Nota Fiscal** e a **Quantidade** do quadro de transporte.")

    arquivos = st.file_uploader(
        "Importar PDFs",
        type=["pdf"],
        accept_multiple_files=True,
        help="Pode selecionar vários PDFs de uma vez.",
    )

    if not arquivos:
        st.info("Aguardando os PDFs...")
        return

    if st.button("Processar PDFs", type="primary"):
        todos: list[ResultadoDanfe] = []
        barra = st.progress(0)
        status = st.empty()

        for i, arq in enumerate(arquivos, start=1):
            status.write(f"Processando {i}/{len(arquivos)}: {arq.name}")
            pdf_bytes = arq.read()
            try:
                todos.extend(extrair_danfes_do_pdf(pdf_bytes, arq.name))
            except Exception as e:
                todos.append(
                    ResultadoDanfe(
                        arquivo=arq.name,
                        numero_nf=None,
                        quantidade=None,
                        pagina=None,
                        observacao=f"Erro: {e}",
                    )
                )
            barra.progress(i / len(arquivos))

        df = pd.DataFrame([r.__dict__ for r in todos])
        df = df.rename(columns={
            "arquivo": "Arquivo",
            "numero_nf": "Numero_NF",
            "quantidade": "Quantidade",
            "pagina": "Pagina",
            "observacao": "Observacao",
        })

        st.success("Processamento concluído!")
        st.dataframe(df, use_container_width=True)

        excel_bytes = gerar_excel(df)
        st.download_button(
            "Baixar Excel",
            data=excel_bytes,
            file_name="resultado_danfe.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )


# -----------------------------
# Modo terminal opcional
# -----------------------------

def app_cli(caminhos: Iterable[str]) -> None:
    todos: list[ResultadoDanfe] = []
    for caminho in caminhos:
        path = Path(caminho)
        if path.suffix.lower() != ".pdf":
            continue
        todos.extend(extrair_danfes_do_pdf(path.read_bytes(), path.name))

    df = pd.DataFrame([r.__dict__ for r in todos])
    df = df.rename(columns={
        "arquivo": "Arquivo",
        "numero_nf": "Numero_NF",
        "quantidade": "Quantidade",
        "pagina": "Pagina",
        "observacao": "Observacao",
    })
    saida = Path("resultado_danfe.xlsx")
    saida.write_bytes(gerar_excel(df))
    print(df.to_string(index=False))
    print(f"\nExcel salvo em: {saida.resolve()}")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        app_cli(sys.argv[1:])
    else:
        app_streamlit()
