from __future__ import annotations

import io
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import fitz  # PyMuPDF
import pandas as pd

@dataclass
class ResultadoDanfe:
    arquivo: str
    numero_nf: str | None
    quantidade: str | None
    pagina: int | None
    observacao: str = ""

# Helpers gerais

def so_numeros(texto: str | None) -> str | None:
    if not texto:
        return None
    limpo = re.sub(r"\D", "", str(texto))
    return limpo or None



# Extração do número da NF-e


def buscar_numero_nf_no_texto(texto: str) -> str | None:
    padroes = [
        r"NF-?e\s*N[ºo°\.]*\s*(\d{5,12})",
        r"N[ºo°\.]\s*(\d{5,12})\s*S[ÉE]RIE",
        r"(?:DANF-?e|DANFE).*?N[ºo°\.]*\s*(\d{5,12})",
    ]
    for p in padroes:
        m = re.search(p, texto, flags=re.IGNORECASE | re.DOTALL)
        if m:
            return so_numeros(m.group(1))

    # fallback: número grande perto de "NF-e" ou "SÉRIE" em qualquer linha
    linhas = [l.strip() for l in texto.splitlines() if l.strip()]
    for i, linha in enumerate(linhas):
        bloco = " ".join(linhas[max(0, i - 2): i + 3])
        if re.search(r"NF-?e|S[ÉE]RIE", bloco, re.IGNORECASE):
            nums = re.findall(r"\b\d{5,12}\b", bloco)
            if nums:
                return nums[0]

    return None


def buscar_numero_nf_por_coordenada(page: fitz.Page) -> str | None:
    """Pega o número no cantinho superior direito, onde fica na maioria dos DANFEs."""
    achados = []
    for w in page.get_text("words"):
        x0, y0, _, _, txt = w[:5]
        if 480 <= x0 <= 590 and 15 <= y0 <= 75 and re.fullmatch(r"\d{5,12}", txt.strip()):
            achados.append((y0, x0, txt.strip()))

    if achados:
        achados.sort()
        return achados[0][2]
    return None

# Extração da quantidade


def buscar_quantidade_por_coordenada(page: fitz.Page) -> str | None:
    """
    Localiza o campo QUANTIDADE dentro do bloco do transportador.
    Usar coordenadas aqui evita pegar a quantidade da tabela de produtos,
    que costuma aparecer bem antes no PDF.
    """
    words = page.get_text("words")
    if not words:
        return None

    labels_qtd = []
    for w in words:
        x0, y0, x1, y1, txt = w[:5]
        if txt.upper().strip() in {"QUANTIDADE", "QTD"}:
            labels_qtd.append((x0, y0, x1, y1))

    for x0, y0, x1, y1 in labels_qtd:
        # o valor fica logo abaixo da etiqueta, dentro da mesma caixa
        abaixo = []
        for ww in words:
            wx0, wy0, _, _, txt = ww[:5]
            if y1 <= wy0 <= y1 + 25 and x0 - 10 <= wx0 <= x0 + 75:
                if re.fullmatch(r"\d{1,9}", txt.strip()):
                    abaixo.append((wy0, wx0, txt.strip()))
        if abaixo:
            abaixo.sort()
            return abaixo[0][2]

    return None


def buscar_quantidade_no_texto(texto: str) -> str | None:
    """
    Fallback por texto corrido. Tenta se limitar à seção de transporte
    pra não pegar quantidade de produto por engano.
    """
    t = re.sub(r"[ \t]+", " ", texto)

    m_secao = re.search(
        r"TRANSPORTADOR.*?QUANTIDADE.*?(?:DADOS DO PRODUTO|DADOS DOS PRODUTOS|C[ÓO]DIGO)",
        t,
        flags=re.IGNORECASE | re.DOTALL,
    )
    secao = m_secao.group(0) if m_secao else t

    m = re.search(r"QUANTIDADE\s+.*?(\b\d{1,7}\b)", secao, flags=re.IGNORECASE | re.DOTALL)
    if m:
        return m.group(1)
    return None



# Processamento principal


def extrair_danfes_do_pdf(pdf_bytes: bytes, nome_arquivo: str) -> list[ResultadoDanfe]:
    resultados: list[ResultadoDanfe] = []
    ja_vistos: set[str] = set()

    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        for idx, page in enumerate(doc, start=1):
            texto = page.get_text("text") or ""
            numero_nf = buscar_numero_nf_por_coordenada(page) or buscar_numero_nf_no_texto(texto)

            if not numero_nf:
                continue

            # mesma NF aparece em várias páginas (2/2, 3/3...) — pula
            if numero_nf in ja_vistos:
                continue

            quantidade = buscar_quantidade_por_coordenada(page) or buscar_quantidade_no_texto(texto)

            # se não achou na página atual, tenta nas próximas da mesma nota
            if not quantidade:
                for i_prox in range(idx, min(idx + 2, len(doc))):
                    p2 = doc[i_prox]
                    texto2 = p2.get_text("text") or ""
                    nf_prox = buscar_numero_nf_por_coordenada(p2) or buscar_numero_nf_no_texto(texto2)
                    if nf_prox == numero_nf:
                        quantidade = buscar_quantidade_por_coordenada(p2) or buscar_quantidade_no_texto(texto2)
                        if quantidade:
                            break

            ja_vistos.add(numero_nf)
            obs = "OK" if quantidade else "Quantidade não localizada no quadro de transporte"
            resultados.append(ResultadoDanfe(nome_arquivo, numero_nf, quantidade, idx, obs))

    if not resultados:
        resultados.append(
            ResultadoDanfe(nome_arquivo, None, None, None, "Nenhuma NF-e encontrada no PDF")
        )

    return resultados



# Exportação para Excel

def gerar_excel(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="DANFE")
        ws = writer.book["DANFE"]
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions
        for col in ws.columns:
            maior = max(len(str(c.value)) if c.value is not None else 0 for c in col)
            ws.column_dimensions[col[0].column_letter].width = min(max(maior + 2, 12), 45)
    buf.seek(0)
    return buf.getvalue()


def montar_dataframe(resultados: list[ResultadoDanfe]) -> pd.DataFrame:
    df = pd.DataFrame([r.__dict__ for r in resultados])
    return df.rename(columns={
        "arquivo": "Arquivo",
        "numero_nf": "Numero_NF",
        "quantidade": "Quantidade",
        "pagina": "Pagina",
        "observacao": "Observacao",
    })


# Interface Streamlit


def app_streamlit() -> None:
    import streamlit as st

    st.set_page_config(page_title="Extrator DANFE", page_icon="📄", layout="centered")
    st.title("📄 Extrator de DANFE / NF-e")
    st.write("Importe os PDFs e o app extrai o **Nº da Nota** e a **Quantidade** do quadro de transporte.")

    arquivos = st.file_uploader(
        "Selecione os PDFs",
        type=["pdf"],
        accept_multiple_files=True,
        help="Pode selecionar vários de uma vez.",
    )

    if not arquivos:
        st.info("Aguardando os PDFs...")
        return

    if st.button("Processar", type="primary"):
        todos: list[ResultadoDanfe] = []
        barra = st.progress(0)
        status = st.empty()

        for i, arq in enumerate(arquivos, start=1):
            status.write(f"Processando {i}/{len(arquivos)}: {arq.name}")
            try:
                todos.extend(extrair_danfes_do_pdf(arq.read(), arq.name))
            except Exception as e:
                todos.append(ResultadoDanfe(arq.name, None, None, None, f"Erro: {e}"))
            barra.progress(i / len(arquivos))

        df = montar_dataframe(todos)
        st.success("Pronto!")
        st.dataframe(df, use_container_width=True)
        st.download_button(
            "Baixar Excel",
            data=gerar_excel(df),
            file_name="resultado_danfe.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )


# Modo terminal

def app_cli(caminhos: Iterable[str]) -> None:
    todos: list[ResultadoDanfe] = []
    for caminho in caminhos:
        path = Path(caminho)
        if path.suffix.lower() != ".pdf":
            continue
        todos.extend(extrair_danfes_do_pdf(path.read_bytes(), path.name))

    df = montar_dataframe(todos)
    saida = Path("resultado_danfe.xlsx")
    saida.write_bytes(gerar_excel(df))
    print(df.to_string(index=False))
    print(f"\nSalvo em: {saida.resolve()}")


# Streamlit

if __name__ == "__main__":
    if len(sys.argv) > 1:
        app_cli(sys.argv[1:])
    else:
        app_streamlit()
