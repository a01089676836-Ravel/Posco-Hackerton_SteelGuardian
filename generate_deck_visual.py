# -*- coding: utf-8 -*-
"""
generate_deck_visual.py
POSCO AI Hackathon Final Presentation Deck (Premium Executive Redesign)
Designed with strict visual hierarchy, roadmaps, metric callout cards,
generous white space, high contrast, and zero text overflow.
"""

import os
import shutil
from pathlib import Path
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN
from pptx.enum.shapes import MSO_SHAPE

def build_visual_deck():
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    blank_layout = prs.slide_layouts[6]

    # Executive Color Palette
    c_white = RGBColor(255, 255, 255)
    c_card_bg = RGBColor(248, 249, 250)         # Soft card surface #F8F9FA
    c_card_border = RGBColor(222, 226, 230)     # Clean border #DEE2E6
    c_card_hover = RGBColor(241, 245, 249)      # Slightly highlighted card
    c_primary = RGBColor(26, 37, 48)            # POSCO Charcoal Navy #1A2530
    c_blue = RGBColor(0, 82, 165)               # POSCO Ocean Blue #0052A5
    c_blue_light = RGBColor(230, 240, 255)      # Soft blue pill bg
    c_accent_green = RGBColor(40, 167, 69)      # Pass / 100% KPI #28A745
    c_accent_orange = RGBColor(230, 126, 34)    # Rework #E67E22
    c_accent_red = RGBColor(220, 53, 69)        # Scrap / Alert #DC3545
    c_text_dark = RGBColor(33, 37, 41)          # #212529
    c_text_sub = RGBColor(73, 80, 87)           # #495057
    c_text_muted = RGBColor(108, 117, 125)      # #6C757D
    c_divider = RGBColor(220, 224, 230)

    def add_header(slide, cat_num, category, title, slide_num):
        # 1. Top subtle accent line
        top_line = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0.0), Inches(0.0), Inches(13.333), Inches(0.08))
        top_line.fill.solid()
        top_line.fill.fore_color.rgb = c_blue
        top_line.line.fill.background()

        # 2. Category Pill / Tracker
        cat_box = slide.shapes.add_textbox(Inches(0.8), Inches(0.35), Inches(8.0), Inches(0.28))
        tf_cat = cat_box.text_frame
        tf_cat.word_wrap = True
        tf_cat.margin_left = tf_cat.margin_right = tf_cat.margin_top = tf_cat.margin_bottom = 0
        p_cat = tf_cat.paragraphs[0]
        p_cat.text = f"{cat_num:02d}  /  {category.upper()}"
        p_cat.font.name = "맑은 고딕"
        p_cat.font.size = Pt(11)
        p_cat.font.bold = True
        p_cat.font.color.rgb = c_blue

        # 3. Slide Title
        t_box = slide.shapes.add_textbox(Inches(0.8), Inches(0.68), Inches(10.5), Inches(0.55))
        tf_t = t_box.text_frame
        tf_t.word_wrap = True
        tf_t.margin_left = tf_t.margin_right = tf_t.margin_top = tf_t.margin_bottom = 0
        p_t = tf_t.paragraphs[0]
        p_t.text = title
        p_t.font.name = "맑은 고딕"
        p_t.font.size = Pt(22)
        p_t.font.bold = True
        p_t.font.color.rgb = c_primary

        # 4. Slide Number Badge (Top Right)
        num_box = slide.shapes.add_textbox(Inches(11.5), Inches(0.35), Inches(1.0), Inches(0.4))
        tf_num = num_box.text_frame
        tf_num.word_wrap = True
        tf_num.margin_left = tf_num.margin_right = tf_num.margin_top = tf_num.margin_bottom = 0
        p_num = tf_num.paragraphs[0]
        p_num.alignment = PP_ALIGN.RIGHT
        p_num.text = f"{slide_num:02d}"
        p_num.font.name = "맑은 고딕"
        p_num.font.size = Pt(14)
        p_num.font.bold = True
        p_num.font.color.rgb = c_text_muted

        # 5. Header Divider Line
        div = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0.8), Inches(1.30), Inches(11.733), Inches(0.015))
        div.fill.solid()
        div.fill.fore_color.rgb = c_divider
        div.line.fill.background()

        # 6. Global Clean Footer
        f_box = slide.shapes.add_textbox(Inches(0.8), Inches(7.12), Inches(11.733), Inches(0.25))
        tf_f = f_box.text_frame
        tf_f.margin_left = tf_f.margin_right = tf_f.margin_top = tf_f.margin_bottom = 0
        p_f = tf_f.paragraphs[0]
        p_f.text = "POSCO AI HACKATHON 2026  ·  스틸가디언 (SteelGuardian)  ·  SSOT: docs/final_metrics.md"
        p_f.font.name = "맑은 고딕"
        p_f.font.size = Pt(9)
        p_f.font.color.rgb = c_text_muted

    def add_card(slide, left, top, width, height, border_color=c_card_border, bg_color=c_card_bg):
        card = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, left, top, width, height)
        card.fill.solid()
        card.fill.fore_color.rgb = bg_color
        card.line.color.rgb = border_color
        card.line.width = Pt(1)
        return card

    # =========================================================================
    # SLIDE 1: 표지 (COVER - Executive Clean & Strong Impact)
    # =========================================================================
    s1 = prs.slides.add_slide(blank_layout)

    # Top accent bar
    top_bar = s1.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0.0), Inches(0.0), Inches(13.333), Inches(0.12))
    top_bar.fill.solid()
    top_bar.fill.fore_color.rgb = c_blue
    top_bar.line.fill.background()

    # Category Pill
    cat1 = s1.shapes.add_textbox(Inches(0.8), Inches(0.8), Inches(8.0), Inches(0.35))
    tf_c1 = cat1.text_frame
    p = tf_c1.paragraphs[0]
    p.text = "POSCO K-뉴딜 아카데미  /  2026 AI 해커톤 최종 발표"
    p.font.name = "맑은 고딕"
    p.font.size = Pt(12)
    p.font.bold = True
    p.font.color.rgb = c_blue

    # Main Big Title Box
    tbox = s1.shapes.add_textbox(Inches(0.8), Inches(1.3), Inches(11.733), Inches(2.8))
    tf1 = tbox.text_frame
    tf1.word_wrap = True
    tf1.margin_left = tf1.margin_right = tf1.margin_top = tf1.margin_bottom = 0

    p_title = tf1.paragraphs[0]
    p_title.text = "스틸가디언 (SteelGuardian)"
    p_title.font.name = "맑은 고딕"
    p_title.font.size = Pt(40)
    p_title.font.bold = True
    p_title.font.color.rgb = c_primary
    p_title.space_after = Pt(8)

    p_sub = tf1.add_paragraph()
    p_sub.text = "PatchCore 비지도 학습 기반 금속 부품 실시간 이상탐지 & 3-Tier 공정 제어 플랫폼"
    p_sub.font.name = "맑은 고딕"
    p_sub.font.size = Pt(18)
    p_sub.font.bold = True
    p_sub.font.color.rgb = c_text_sub
    p_sub.space_after = Pt(12)

    # 3 Key Value Badges (Inline)
    badges = [
        ("30초 고속 온보딩", "Zero-Training"),
        ("무중단 모델 핫스왑", "Zero-Downtime"),
        ("100% 오프라인 폐쇄망", "Air-Gapped")
    ]
    b_w = Inches(3.64)
    b_gap = Inches(0.4)
    for idx, (b_title, b_eng) in enumerate(badges):
        bx = Inches(0.8) + idx * (b_w + b_gap)
        add_card(s1, bx, Inches(3.3), b_w, Inches(0.8), border_color=RGBColor(200, 220, 245), bg_color=RGBColor(245, 249, 255))
        bbox = s1.shapes.add_textbox(bx + Inches(0.2), Inches(3.38), b_w - Inches(0.4), Inches(0.65))
        tf_b = bbox.text_frame
        tf_b.margin_left = tf_b.margin_right = tf_b.margin_top = tf_b.margin_bottom = 0
        pb1 = tf_b.paragraphs[0]
        pb1.text = b_title
        pb1.font.name = "맑은 고딕"
        pb1.font.size = Pt(13)
        pb1.font.bold = True
        pb1.font.color.rgb = c_blue

        pb2 = tf_b.add_paragraph()
        pb2.text = b_eng
        pb2.font.name = "맑은 고딕"
        pb2.font.size = Pt(10)
        pb2.font.color.rgb = c_text_muted

    # Bottom Presenter & Team Card
    add_card(s1, Inches(0.8), Inches(4.5), Inches(11.733), Inches(2.2), border_color=c_card_border, bg_color=c_card_bg)
    teambox = s1.shapes.add_textbox(Inches(1.1), Inches(4.75), Inches(11.133), Inches(1.7))
    tft = teambox.text_frame
    tft.word_wrap = True
    tft.margin_left = tft.margin_right = tft.margin_top = tft.margin_bottom = 0

    pt1 = tft.paragraphs[0]
    pt1.text = "발표자 : 전종현 (Role 5 : 팀장 / PM 및 발표·지표 총괄)"
    pt1.font.name = "맑은 고딕"
    pt1.font.size = Pt(14)
    pt1.font.bold = True
    pt1.font.color.rgb = c_primary
    pt1.space_after = Pt(6)

    pt2 = tft.add_paragraph()
    pt2.text = "팀원 : 김지민 (데이터·평가)  |  차주현 (AI 비전 모델링)  |  허재원 (백엔드·보안)  |  송민지 (프론트엔드·UI/UX)"
    pt2.font.name = "맑은 고딕"
    pt2.font.size = Pt(12)
    pt2.font.color.rgb = c_text_dark
    pt2.space_after = Pt(10)

    pt3 = tft.add_paragraph()
    pt3.text = "핵심 산출물 : 단독 실행 Master Hub HTML  |  REST API 서버  |  실시간 컨베이어 관제 UI  |  115장 실측 벤치마크"
    pt3.font.name = "맑은 고딕"
    pt3.font.size = Pt(11)
    pt3.font.color.rgb = c_text_muted

    # =========================================================================
    # SLIDE 2: 문제 정의 (PROBLEM DEFINITION - Road / 3 Step Visual Pipeline)
    # =========================================================================
    s2 = prs.slides.add_slide(blank_layout)
    add_header(s2, 1, "Problem Definition", "제철 가공 라인이 직면한 3대 현실적 병목 (Pain Points)", 2)

    col_w2 = Inches(3.64)
    col_gap2 = Inches(0.4)
    c_lefts2 = [Inches(0.8) + i * (col_w2 + col_gap2) for i in range(3)]

    probs2 = [
        ("01", "불량 데이터 희소성", "현장 부품의 99.9%는 정상",
         "수천 장의 불량 라벨링이 필요한 지도학습은 현장 도입 불가",
         "비지도 학습(Unsupervised) 기반 정상 기준 모델링이 필수적 대안",
         RGBColor(230, 240, 255), c_blue),
        ("02", "미지의 결함 오판 위험", "사전 정의되지 않은 돌발 결함",
         "미세 크랙, 긁힘, 변색 발생 시 일반 지도학습은 정상으로 오판",
         "정상 특징 분포와의 국소 거리 편차를 측정하는 이상탐지 필수",
         RGBColor(255, 243, 230), c_accent_orange),
        ("03", "폐쇄망 & 규격 전환 지연", "외부 인터넷 차단 폐쇄망 환경",
         "보안 규정상 클라우드 차단 및 신규 규격 투입마다 재학습 병목",
         "CPU 100ms 내 초고속 추론 및 30초 내 무학습 온보딩 필요",
         RGBColor(245, 240, 255), RGBColor(110, 60, 200))
    ]

    for idx, (p_num, p_title, p_sub, b1, b2, bg_tint, stroke_tint) in enumerate(probs2):
        l = c_lefts2[idx]
        add_card(s2, l, Inches(1.6), col_w2, Inches(5.1), border_color=stroke_tint, bg_color=c_card_bg)

        # Top Badge Card
        top_badge = s2.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, l + Inches(0.3), Inches(1.9), Inches(0.8), Inches(0.45))
        top_badge.fill.solid()
        top_badge.fill.fore_color.rgb = stroke_tint
        top_badge.line.fill.background()
        tf_tb = top_badge.text_frame
        tf_tb.margin_left = tf_tb.margin_right = tf_tb.margin_top = tf_tb.margin_bottom = 0
        p_tb = tf_tb.paragraphs[0]
        p_tb.alignment = PP_ALIGN.CENTER
        p_tb.text = p_num
        p_tb.font.name = "맑은 고딕"
        p_tb.font.size = Pt(14)
        p_tb.font.bold = True
        p_tb.font.color.rgb = c_white

        # Content Box
        pbox = s2.shapes.add_textbox(l + Inches(0.3), Inches(2.55), col_w2 - Inches(0.6), Inches(3.9))
        tf_p = pbox.text_frame
        tf_p.word_wrap = True
        tf_p.margin_left = tf_p.margin_right = tf_p.margin_top = tf_p.margin_bottom = 0

        p1 = tf_p.paragraphs[0]
        p1.text = p_title
        p1.font.name = "맑은 고딕"
        p1.font.size = Pt(17)
        p1.font.bold = True
        p1.font.color.rgb = c_primary
        p1.space_after = Pt(4)

        p2 = tf_p.add_paragraph()
        p2.text = p_sub
        p2.font.name = "맑은 고딕"
        p2.font.size = Pt(11)
        p2.font.bold = True
        p2.font.color.rgb = stroke_tint
        p2.space_after = Pt(20)

        # 2 Key Summary Points (Concise, no overflow)
        p_b1_title = tf_p.add_paragraph()
        p_b1_title.text = "현실적 한계"
        p_b1_title.font.name = "맑은 고딕"
        p_b1_title.font.size = Pt(12)
        p_b1_title.font.bold = True
        p_b1_title.font.color.rgb = c_text_dark
        p_b1_title.space_after = Pt(2)

        p_b1_desc = tf_p.add_paragraph()
        p_b1_desc.text = b1
        p_b1_desc.font.name = "맑은 고딕"
        p_b1_desc.font.size = Pt(10.5)
        p_b1_desc.font.color.rgb = c_text_sub
        p_b1_desc.space_after = Pt(16)

        p_b2_title = tf_p.add_paragraph()
        p_b2_title.text = "스틸가디언 해법"
        p_b2_title.font.name = "맑은 고딕"
        p_b2_title.font.size = Pt(12)
        p_b2_title.font.bold = True
        p_b2_title.font.color.rgb = c_blue
        p_b2_title.space_after = Pt(2)

        p_b2_desc = tf_p.add_paragraph()
        p_b2_desc.text = b2
        p_b2_desc.font.name = "맑은 고딕"
        p_b2_desc.font.size = Pt(10.5)
        p_b2_desc.font.color.rgb = c_text_sub

    # =========================================================================
    # SLIDE 3: 시스템 아키텍처 (SYSTEM ARCHITECTURE - Diagram + Clean Split)
    # =========================================================================
    s3 = prs.slides.add_slide(blank_layout)
    add_header(s3, 2, "System Architecture", "PatchCore Eq.6·7 기반 End-to-End 무누수 품질 관제 파이프라인", 3)

    # Top Visual Diagram
    s3.shapes.add_picture("docs/figures/pipeline_diagram.png", Inches(0.8), Inches(1.5), Inches(11.733), Inches(3.2))

    # Bottom 2 Structured Cards (Algorithm & 3-Tier)
    c3_w = Inches(5.7)
    add_card(s3, Inches(0.8), Inches(4.9), c3_w, Inches(2.0), border_color=c_card_border, bg_color=c_card_bg)
    b3_1 = s3.shapes.add_textbox(Inches(1.1), Inches(5.05), c3_w - Inches(0.6), Inches(1.7))
    tf3_1 = b3_1.text_frame
    tf3_1.word_wrap = True
    tf3_1.margin_left = tf3_1.margin_right = tf3_1.margin_top = tf3_1.margin_bottom = 0

    p = tf3_1.paragraphs[0]
    p.text = "Pure PyTorch PatchCore 고속 추론 엔진"
    p.font.name = "맑은 고딕"
    p.font.size = Pt(13)
    p.font.bold = True
    p.font.color.rgb = c_primary
    p.space_after = Pt(8)

    pts3_1 = [
        "ResNet18 Layer2+Layer3 특징 추출 : 오프라인 로컬 가중치 사용",
        "Eq.6 Greedy Coreset 10% 압축 : 메모리 90% 절감 및 CPU 103ms 달성",
        "Eq.7 밀도 재가중치 점수화 : 최근접 이웃 거리 기반 국소 이상치 검출"
    ]
    for pt in pts3_1:
        pb = tf3_1.add_paragraph()
        pb.text = "• " + pt
        pb.font.name = "맑은 고딕"
        pb.font.size = Pt(10)
        pb.font.color.rgb = c_text_dark
        pb.space_after = Pt(4)

    add_card(s3, Inches(6.833), Inches(4.9), c3_w, Inches(2.0), border_color=c_card_border, bg_color=c_card_bg)
    b3_2 = s3.shapes.add_textbox(Inches(7.133), Inches(5.05), c3_w - Inches(0.6), Inches(1.7))
    tf3_2 = b3_2.text_frame
    tf3_2.word_wrap = True
    tf3_2.margin_left = tf3_2.margin_right = tf3_2.margin_top = tf3_2.margin_bottom = 0

    p = tf3_2.paragraphs[0]
    p.text = "3-Tier 공정 제어 및 조업 의사결정 (Rule Engine)"
    p.font.name = "맑은 고딕"
    p.font.size = Pt(13)
    p.font.bold = True
    p.font.color.rgb = c_blue
    p.space_after = Pt(8)

    pts3_2 = [
        "PASS (th < 0.600) : 정상 통과 / 히트맵 자동 억제로 조업자 피로 차단",
        "REWORK (0.600 <= th < 0.700) : 결함 히트맵 표시 및 2차 육안 플래그 활성화",
        "SCRAP (th >= 0.700) : 설비 인터록 즉시 발동 / 정상품 오폐기 0.00% (0건)"
    ]
    for pt in pts3_2:
        pb = tf3_2.add_paragraph()
        pb.text = "• " + pt
        pb.font.name = "맑은 고딕"
        pb.font.size = Pt(10)
        pb.font.color.rgb = c_text_dark
        pb.space_after = Pt(4)

    # =========================================================================
    # SLIDE 4: 벤치마크 및 결함 실측 (BENCHMARK - Image Grid + Clean KPI Table)
    # =========================================================================
    s4 = prs.slides.add_slide(blank_layout)
    add_header(s4, 3, "Benchmark Performance", "MVTec Metal Nut 115장 전수 평가 및 실측 결함 히트맵", 4)

    # Left: Image Grid
    s4.shapes.add_picture("docs/figures/inspection_samples_grid.png", Inches(0.8), Inches(1.5), Inches(5.8), Inches(4.2))

    # Right: Metric Table
    rows = 6
    cols = 3
    t_left = Inches(6.8)
    t_top = Inches(1.5)
    t_width = Inches(5.733)
    t_height = Inches(4.2)

    table_shape = s4.shapes.add_table(rows, cols, t_left, t_top, t_width, t_height)
    t = table_shape.table
    t.columns[0].width = Inches(2.2)
    t.columns[1].width = Inches(1.4)
    t.columns[2].width = Inches(2.133)

    t_data = [
        ("지표 범주", "실측값", "측정 기준 / 공학적 비고"),
        ("불량 검출 Recall (SAFETY)", "100.00% (FN=0)", "th=0.600 / 불량 93장 전수 검출"),
        ("불량 검출 Recall (BALANCED)", "97.85% (FN=2)", "th=0.645 / 정상 오경보 4.55% 억제"),
        ("5-Seed 교차검증 신뢰구간", "97.85% ~ 100%", "Seed 42, 7, 123, 2026, 999 분할"),
        ("CPU 단일 추론 지연시간", "103.4 ms", "AMD 5500U / 8~10 UPH 고속 대응"),
        ("정상 부품 오폐기 손실", "0.00% (0건)", "SCRAP 오판 제로 / 고가 부품 보존")
    ]

    for r_idx, row in enumerate(t_data):
        for c_idx, cell_value in enumerate(row):
            cell = t.cell(r_idx, c_idx)
            cell.text = cell_value
            p = cell.text_frame.paragraphs[0]
            p.alignment = PP_ALIGN.CENTER if c_idx == 1 else (PP_ALIGN.CENTER if r_idx == 0 else PP_ALIGN.LEFT)
            p.font.name = "맑은 고딕"
            p.font.size = Pt(9.5)
            if r_idx == 0:
                p.font.bold = True
                p.font.color.rgb = c_white
                cell.fill.solid()
                cell.fill.fore_color.rgb = c_primary
            else:
                cell.fill.solid()
                cell.fill.fore_color.rgb = RGBColor(255, 255, 255) if r_idx % 2 == 1 else RGBColor(245, 248, 252)
                if c_idx == 1:
                    p.font.bold = True
                    p.font.color.rgb = c_blue if "100" in cell_value or "0.00" in cell_value else c_accent_orange
                else:
                    p.font.color.rgb = c_text_dark

    # Bottom Notice Banner (Clean single paragraph, no overflow)
    add_card(s4, Inches(0.8), Inches(5.9), Inches(11.733), Inches(1.0), border_color=RGBColor(240, 200, 150), bg_color=RGBColor(255, 250, 240))
    box_n = s4.shapes.add_textbox(Inches(1.1), Inches(6.0), Inches(11.133), Inches(0.8))
    tf_n = box_n.text_frame
    tf_n.word_wrap = True
    tf_n.margin_left = tf_n.margin_right = tf_n.margin_top = tf_n.margin_bottom = 0

    pn1 = tf_n.paragraphs[0]
    pn1.text = "공학적 트레이드오프 (Fact-Grounding)"
    pn1.font.name = "맑은 고딕"
    pn1.font.size = Pt(11)
    pn1.font.bold = True
    pn1.font.color.rgb = RGBColor(180, 80, 0)
    pn1.space_after = Pt(2)

    pn2 = tf_n.add_paragraph()
    pn2.text = "SAFETY 모드에서 정상품 22장 중 3건(13.6%)이 안전 마진으로 인해 REWORK로 분류되나, SCRAP(오폐기)는 0%입니다. 불량 1건 유출로 인한 고객사 클레임 손실이 육안 재확인 비용보다 크므로 안전 마진을 최우선 확보했습니다."
    pn2.font.name = "맑은 고딕"
    pn2.font.size = Pt(9.5)
    pn2.font.color.rgb = c_text_dark

    # =========================================================================
    # SLIDE 5: 강건성 검증 (ROBUSTNESS AUDIT - Bar Chart + Defense Strategy)
    # =========================================================================
    s5 = prs.slides.add_slide(blank_layout)
    add_header(s5, 4, "Robustness Audit", "카메라 악조건 7대 섭동 스트레스 테스트 및 한계 방어 논리", 5)

    # Left: Robustness Chart
    s5.shapes.add_picture("docs/figures/robustness_chart.png", Inches(0.8), Inches(1.5), Inches(6.0), Inches(4.2))

    # Right: Analysis Card
    c5_w = Inches(5.533)
    add_card(s5, Inches(7.0), Inches(1.5), c5_w, Inches(4.2), border_color=c_card_border, bg_color=c_card_bg)
    b5 = s5.shapes.add_textbox(Inches(7.2), Inches(1.7), c5_w - Inches(0.4), Inches(3.8))
    tf5 = b5.text_frame
    tf5.word_wrap = True
    tf5.margin_left = tf5.margin_right = tf5.margin_top = tf5.margin_bottom = 0

    p = tf5.paragraphs[0]
    p.text = "경계 취약 샘플 (color/004.png) 정직한 분석 및 극복"
    p.font.name = "맑은 고딕"
    p.font.size = Pt(13)
    p.font.bold = True
    p.font.color.rgb = c_primary
    p.space_after = Pt(6)

    bullets_s5 = [
        ("취약점 원인", "color/004.png는 원본 점수 0.6013인 경계 샘플로, 조도 10% 감소 시 점수 0.5843으로 하강하여 유일하게 PASS 오판 발생 (Recall 98.92%)"),
        ("치명 불량 100% 보존", "Cracked, Bent 등 구조적 치명 결함은 7대 섭동 전 시나리오에서 Recall 100% 및 SCRAP 판정 유지"),
        ("하드웨어 대책", "조도 편차 방지를 위한 고주파 링 조명 + 밀폐형 차광 챔버 구축으로 환경 변수 물리적 차단"),
        ("소프트웨어 대책", "배경 기준 ROI 히스토그램 평활화 전처리를 통해 조도 변화에 대한 불변성 확보")
    ]
    for title, desc in bullets_s5:
        pb = tf5.add_paragraph()
        pb.text = f"• {title} : {desc}"
        pb.font.name = "맑은 고딕"
        pb.font.size = Pt(9.5)
        pb.font.color.rgb = c_text_dark
        pb.space_after = Pt(5)

    # Bottom Banner
    add_card(s5, Inches(0.8), Inches(5.9), Inches(11.733), Inches(1.0), border_color=c_card_border, bg_color=c_card_bg)
    box_5b = s5.shapes.add_textbox(Inches(1.1), Inches(6.0), Inches(11.133), Inches(0.8))
    tf_5b = box_5b.text_frame
    tf_5b.word_wrap = True
    tf_5b.margin_left = tf_5b.margin_right = tf_5b.margin_top = tf_5b.margin_bottom = 0

    p_5b = tf_5b.paragraphs[0]
    p_5b.text = "심사위원 질의 방어 포인트 (정직한 기술 검증)"
    p_5b.font.name = "맑은 고딕"
    p_5b.font.size = Pt(11)
    p_5b.font.bold = True
    p_5b.font.color.rgb = c_blue
    p_5b.space_after = Pt(2)

    p_5b2 = tf_5b.add_paragraph()
    p_5b2.text = "'모든 환경 100% 무결점'이라는 과대 주장을 배제하고, 실측 805회 스트레스 테스트를 통해 유일한 한계점(color/004.png)을 명확히 제시하고 조명 챔버 및 전처리 극복 방안을 선제 제시함으로써 기술적 신뢰성을 확보합니다."
    p_5b2.font.name = "맑은 고딕"
    p_5b2.font.size = Pt(9.5)
    p_5b2.font.color.rgb = c_text_dark

    # =========================================================================
    # SLIDE 6: 운영 및 온보딩 (OPERATIONS & MLOPS - 2 Wide Visual Cards)
    # =========================================================================
    s6 = prs.slides.add_slide(blank_layout)
    add_header(s6, 5, "Operations & MLOps", "30초 Zero-Training 온보딩 및 무중단 원자적 모델 핫스왑", 6)

    col_w6 = Inches(5.7)
    add_card(s6, Inches(0.8), Inches(1.6), col_w6, Inches(5.1), border_color=c_card_border, bg_color=c_card_bg)
    b6_1 = s6.shapes.add_textbox(Inches(1.1), Inches(1.9), col_w6 - Inches(0.6), Inches(4.5))
    tf6_1 = b6_1.text_frame
    tf6_1.word_wrap = True
    tf6_1.margin_left = tf6_1.margin_right = tf6_1.margin_top = tf6_1.margin_bottom = 0

    p = tf6_1.paragraphs[0]
    p.text = "신규 부품 Zero-Training 온보딩"
    p.font.name = "맑은 고딕"
    p.font.size = Pt(16)
    p.font.bold = True
    p.font.color.rgb = c_primary
    p.space_after = Pt(4)

    p_sub = tf6_1.add_paragraph()
    p_sub.text = "라인 정지 없는 신속한 다품종 규격 교체"
    p_sub.font.name = "맑은 고딕"
    p_sub.font.size = Pt(11)
    p_sub.font.bold = True
    p_sub.font.color.rgb = c_blue
    p_sub.space_after = Pt(16)

    bullets_s6_1 = [
        ("GPU 역전파 배제", "정상 이미지 투입 시 Coreset 특징 선택으로 메모리 뱅크 즉시 구축"),
        ("30초 SLA 실측", "신규 규격 온보딩 소요시간 실측 28.4초 (정상 부품 50장 기준 완결)"),
        ("임계치 자동 산출", "정상 검증셋(20장) 추론 점수의 μ + 3σ 기반 안전 임계치(0.600) 자동 산출"),
        ("현장 작업자 편의", "AI 엔지니어 개입 없이 조업자가 사진 투입 버튼 클릭만으로 즉시 모델 등록")
    ]
    for title, desc in bullets_s6_1:
        pb = tf6_1.add_paragraph()
        pb.text = f"• {title} : {desc}"
        pb.font.name = "맑은 고딕"
        pb.font.size = Pt(10.5)
        pb.font.color.rgb = c_text_dark
        pb.space_after = Pt(12)

    add_card(s6, Inches(6.833), Inches(1.6), col_w6, Inches(5.1), border_color=c_card_border, bg_color=c_card_bg)
    b6_2 = s6.shapes.add_textbox(Inches(7.133), Inches(1.9), col_w6 - Inches(0.6), Inches(4.5))
    tf6_2 = b6_2.text_frame
    tf6_2.word_wrap = True
    tf6_2.margin_left = tf6_2.margin_right = tf6_2.margin_top = tf6_2.margin_bottom = 0

    p = tf6_2.paragraphs[0]
    p.text = "무중단 원자적 모델 핫스왑 (Atomic Hot-Swap)"
    p.font.name = "맑은 고딕"
    p.font.size = Pt(16)
    p.font.bold = True
    p.font.color.rgb = c_primary
    p.space_after = Pt(4)

    p_sub2 = tf6_2.add_paragraph()
    p_sub2.text = "POST /v1/models/activate API 기반 무중단 교체"
    p_sub2.font.name = "맑은 고딕"
    p_sub2.font.size = Pt(11)
    p_sub2.font.bold = True
    p_sub2.font.color.rgb = c_blue
    p_sub2.space_after = Pt(16)

    bullets_s6_2 = [
        ("라인 셧다운 제로", "FastAPI 서버 프로세스 재기동 없이 새 부품 엔진 원자적 교체"),
        ("스레드 안전성 보장", "threading.Lock 적용으로 실시간 추론 도중 스왑 요청 시에도 에러 제로"),
        ("Fail-Safe 롤백 망", "신규 모델 로드 실패 시 직전 안정 버전 유지 및 즉시 롤백 지원"),
        ("Audit 감사 동기화", "모델 변경 시각, 대상 모델 ID, 변경자 정보가 MES 감사 로그에 100% 자동 기록")
    ]
    for title, desc in bullets_s6_2:
        pb = tf6_2.add_paragraph()
        pb.text = f"• {title} : {desc}"
        pb.font.name = "맑은 고딕"
        pb.font.size = Pt(10.5)
        pb.font.color.rgb = c_text_dark
        pb.space_after = Pt(12)

    # =========================================================================
    # SLIDE 7: 신뢰성 및 MES 감사 (RELIABILITY - Dual Chart + Audit Matching)
    # =========================================================================
    s7 = prs.slides.add_slide(blank_layout)
    add_header(s7, 6, "Reliability & MES Audit", "200건 연속 부하 실측 및 멀티프로세스 파일 락 무유실 검증", 7)

    # Left: Stress Test Chart
    s7.shapes.add_picture("docs/figures/stress_test_chart.png", Inches(0.8), Inches(1.5), Inches(6.0), Inches(4.2))

    # Right: Reliability Card
    c7_w = Inches(5.533)
    add_card(s7, Inches(7.0), Inches(1.5), c7_w, Inches(4.2), border_color=c_card_border, bg_color=c_card_bg)
    b7 = s7.shapes.add_textbox(Inches(7.2), Inches(1.7), c7_w - Inches(0.4), Inches(3.8))
    tf7 = b7.text_frame
    tf7.word_wrap = True
    tf7.margin_left = tf7.margin_right = tf7.margin_top = tf7.margin_bottom = 0

    p = tf7.paragraphs[0]
    p.text = "공장 MES 감사 로그 무결성 (audit_logger.py)"
    p.font.name = "맑은 고딕"
    p.font.size = Pt(13)
    p.font.bold = True
    p.font.color.rgb = c_primary
    p.space_after = Pt(6)

    bullets_s7 = [
        ("200건 1:1 무유실 매칭", "부하 전 341행 -> 부하 후 정확히 541행 (+200행 일치, 로그 유실률 0.00%)"),
        ("멀티프로세스 파일 락", "Windows portalocker 기반 파일 락으로 동시 다발적 추론 시 CSV 경합 차단"),
        ("정밀 메트릭 기록", "판정마다 timestamp, image_id, anomaly_score, decision, latency_ms 정밀 기록"),
        ("100% 로컬 오프라인", "외부 DB 의존 없이 로컬 원자적 파일 로깅 지원으로 폐쇄망 완벽 적합")
    ]
    for title, desc in bullets_s7:
        pb = tf7.add_paragraph()
        pb.text = f"• {title} : {desc}"
        pb.font.name = "맑은 고딕"
        pb.font.size = Pt(9.5)
        pb.font.color.rgb = c_text_dark
        pb.space_after = Pt(5)

    # Bottom Banner
    add_card(s7, Inches(0.8), Inches(5.9), Inches(11.733), Inches(1.0), border_color=c_card_border, bg_color=c_card_bg)
    box_7b = s7.shapes.add_textbox(Inches(1.1), Inches(6.0), Inches(11.133), Inches(0.8))
    tf_7b = box_7b.text_frame
    tf_7b.word_wrap = True
    tf_7b.margin_left = tf_7b.margin_right = tf_7b.margin_top = tf_7b.margin_bottom = 0

    p_7b = tf_7b.paragraphs[0]
    p_7b.text = "장기 운용 안정성 실측 요약 (Memory Leak Zero)"
    p_7b.font.name = "맑은 고딕"
    p_7b.font.size = Pt(11)
    p_7b.font.bold = True
    p_7b.font.color.rgb = c_blue
    p_7b.space_after = Pt(2)

    p_7b2 = tf_7b.add_paragraph()
    p_7b2.text = "200건 연속 풀-트랜잭션 부하 중 서버 RSS 메모리 누수 0 (초기 218.4MB -> 종료 209.9MB, Δ-8.5MB)이며, 평균 지연시간은 277.2ms (P95 331.9ms)로 장기 가동 시에도 성능 저하 없는 철저한 안정성을 보증합니다."
    p_7b2.font.name = "맑은 고딕"
    p_7b2.font.size = Pt(9.5)
    p_7b2.font.color.rgb = c_text_dark

    # =========================================================================
    # SLIDE 8: 라이브 시연 (LIVE DEMO - 3 Step Roadmap Cards)
    # =========================================================================
    s8 = prs.slides.add_slide(blank_layout)
    add_header(s8, 7, "Live Demonstration", "실시간 검사, 30초 온보딩 및 무중단 핫스왑 3단계 라이브 시연", 8)

    col_w8 = Inches(3.64)
    c_lefts8 = [Inches(0.8) + i * (col_w8 + col_gap2) for i in range(3)]

    demos8 = [
        ("시연 1 (30초)", "가상 컨베이어 스트리밍", "초당 수 장 실시간 판정",
         ["웹 대시보드(localhost:8000) 접속",
          "컨베이어 벨트 모의 영상 고속 스트리밍",
          "정상품 PASS 및 스크래치 결함 검출",
          "국소 부위 히트맵 오버레이 및 103ms 체감"]),
        ("시연 2 (30초)", "30초 신규 부품 온보딩", "Zero-Training 고속 구축",
         ["신규 부품 정상 이미지 50장 폴더 지정",
          "'온보딩 시작' 클릭 -> Coreset 추출",
          "28.4초 만에 신규 모델 및 임계치 자동 생성",
          "GPU 재학습 없이 조업자가 즉시 규격 대응"]),
        ("시연 3 (30초)", "무중단 모델 핫스왑", "원자적 교체 및 감사 동기화",
         ["컨베이어 스트리밍 가동 상태 유지",
          "POST /v1/models/activate 호출",
          "이미지 드롭 없이 즉시 신규 부품 판정 전환",
          "MES 감사 로그에 교체 이력 1:1 기록 확인"])
    ]

    for idx, (d_time, d_title, d_sub, d_bullets) in enumerate(demos8):
        l = c_lefts8[idx]
        add_card(s8, l, Inches(1.6), col_w8, Inches(5.1), border_color=c_card_border, bg_color=c_card_bg)

        # Demo Time Badge
        nb = s8.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, l + Inches(0.3), Inches(1.9), Inches(1.5), Inches(0.4))
        nb.fill.solid()
        nb.fill.fore_color.rgb = c_blue
        nb.line.fill.background()
        tf_nb = nb.text_frame
        tf_nb.margin_left = tf_nb.margin_right = tf_nb.margin_top = tf_nb.margin_bottom = 0
        p_nb = tf_nb.paragraphs[0]
        p_nb.alignment = PP_ALIGN.CENTER
        p_nb.text = d_time
        p_nb.font.name = "맑은 고딕"
        p_nb.font.size = Pt(11)
        p_nb.font.bold = True
        p_nb.font.color.rgb = c_white

        # Content Box
        dbox = s8.shapes.add_textbox(l + Inches(0.3), Inches(2.45), col_w8 - Inches(0.6), Inches(4.0))
        tf_d = dbox.text_frame
        tf_d.word_wrap = True
        tf_d.margin_left = tf_d.margin_right = tf_d.margin_top = tf_d.margin_bottom = 0

        p1 = tf_d.paragraphs[0]
        p1.text = d_title
        p1.font.name = "맑은 고딕"
        p1.font.size = Pt(16)
        p1.font.bold = True
        p1.font.color.rgb = c_primary
        p1.space_after = Pt(4)

        p2 = tf_d.add_paragraph()
        p2.text = d_sub
        p2.font.name = "맑은 고딕"
        p2.font.size = Pt(11)
        p2.font.bold = True
        p2.font.color.rgb = c_blue
        p2.space_after = Pt(16)

        for b in d_bullets:
            pb = tf_d.add_paragraph()
            pb.text = "• " + b
            pb.font.name = "맑은 고딕"
            pb.font.size = Pt(10.5)
            pb.font.color.rgb = c_text_dark
            pb.space_after = Pt(10)

    # =========================================================================
    # SLIDE 9: 미래 확장성 (FUTURE SCALABILITY - 2 Column Roadmap)
    # =========================================================================
    s9 = prs.slides.add_slide(blank_layout)
    add_header(s9, 8, "Future Scalability", "다품종 혼류 라인을 위한 ModelRegistry + LRUModelCache 확장 아키텍처", 9)

    add_card(s9, Inches(0.8), Inches(1.6), col_w6, Inches(5.1), border_color=c_card_border, bg_color=c_card_bg)
    b9_1 = s9.shapes.add_textbox(Inches(1.1), Inches(1.9), col_w6 - Inches(0.6), Inches(4.5))
    tf9_1 = b9_1.text_frame
    tf9_1.word_wrap = True
    tf9_1.margin_left = tf9_1.margin_right = tf9_1.margin_top = tf9_1.margin_bottom = 0

    p = tf9_1.paragraphs[0]
    p.text = "현재 버전 전제 및 혼류 생산 병목"
    p.font.name = "맑은 고딕"
    p.font.size = Pt(16)
    p.font.bold = True
    p.font.color.rgb = c_primary
    p.space_after = Pt(4)

    p_sub = tf9_1.add_paragraph()
    p_sub.text = "단일 라인 검증 전제와 현실적 한계"
    p_sub.font.name = "맑은 고딕"
    p_sub.font.size = Pt(11)
    p_sub.font.bold = True
    p_sub.font.color.rgb = c_accent_orange
    p_sub.space_after = Pt(16)

    bullets_s9_1 = [
        ("단일 라인 검증", "현재 구현 버전은 단일 라인, 1개 활성 모델(Single Active) 기준으로 검증"),
        ("혼류 전환 오버헤드", "Nut, Bolt, Plate 등 여러 규격이 혼류 유입될 경우 매번 모델 스왑 오버헤드 발생"),
        ("메모리 상주 한계", "여러 품종의 메모리 뱅크를 동시에 RAM에 올리지 못할 경우 캐시 미스 발생"),
        ("확장 설계 필요성", "제철소 전체 라인 수평 전파를 위해 다품종 동시 서빙 캐시 아키텍처 요구")
    ]
    for title, desc in bullets_s9_1:
        pb = tf9_1.add_paragraph()
        pb.text = f"• {title} : {desc}"
        pb.font.name = "맑은 고딕"
        pb.font.size = Pt(10.5)
        pb.font.color.rgb = c_text_dark
        pb.space_after = Pt(12)

    add_card(s9, Inches(6.833), Inches(1.6), col_w6, Inches(5.1), border_color=c_card_border, bg_color=c_card_bg)
    b9_2 = s9.shapes.add_textbox(Inches(7.133), Inches(1.9), col_w6 - Inches(0.6), Inches(4.5))
    tf9_2 = b9_2.text_frame
    tf9_2.word_wrap = True
    tf9_2.margin_left = tf9_2.margin_right = tf9_2.margin_top = tf9_2.margin_bottom = 0

    p = tf9_2.paragraphs[0]
    p.text = "LRUModelCache 확장 아키텍처 (설계 완료)"
    p.font.name = "맑은 고딕"
    p.font.size = Pt(16)
    p.font.bold = True
    p.font.color.rgb = c_primary
    p.space_after = Pt(4)

    p_sub2 = tf9_2.add_paragraph()
    p_sub2.text = "ModelRegistry + Top-K 인메모리 캐싱"
    p_sub2.font.name = "맑은 고딕"
    p_sub2.font.size = Pt(11)
    p_sub2.font.bold = True
    p_sub2.font.color.rgb = c_blue
    p_sub2.space_after = Pt(16)

    bullets_s9_2 = [
        ("품종 지정 라우팅", "POST /v1/defects/inspect 시 part_id 명시 호출로 적합 모델 즉시 매핑"),
        ("Top-K 인메모리 캐싱", "최빈 5대 품종 모델을 RAM에 상시 캐싱(품종당 15MB)하여 0ms 스왑 달성"),
        ("온디맨드 프리패칭", "비주류 품종 유입 시 로컬 NVMe SSD에서 50ms 내 백그라운드 로딩"),
        ("제철 전 라인 전파", "선재, 열연 코일 표면, 슬라브 결함 등 포스코 전 공정으로 즉시 확장 가능")
    ]
    for title, desc in bullets_s9_2:
        pb = tf9_2.add_paragraph()
        pb.text = f"• {title} : {desc}"
        pb.font.name = "맑은 고딕"
        pb.font.size = Pt(10.5)
        pb.font.color.rgb = c_text_dark
        pb.space_after = Pt(12)

    # =========================================================================
    # SLIDE 10: 가치 및 최종 산출물 (VALUE & DELIVERABLES)
    # =========================================================================
    s10 = prs.slides.add_slide(blank_layout)
    add_header(s10, 9, "Value & Deliverables", "제철소 스마트팩토리 품질 혁신 및 100% 오프라인 구동 완성", 10)

    add_card(s10, Inches(0.8), Inches(1.6), col_w6, Inches(5.1), border_color=c_card_border, bg_color=c_card_bg)
    b10_1 = s10.shapes.add_textbox(Inches(1.1), Inches(1.9), col_w6 - Inches(0.6), Inches(4.5))
    tf10_1 = b10_1.text_frame
    tf10_1.word_wrap = True
    tf10_1.margin_left = tf10_1.margin_right = tf10_1.margin_top = tf10_1.margin_bottom = 0

    p = tf10_1.paragraphs[0]
    p.text = "도입 시 기대 효과 (Business Impact)"
    p.font.name = "맑은 고딕"
    p.font.size = Pt(16)
    p.font.bold = True
    p.font.color.rgb = c_primary
    p.space_after = Pt(4)

    p_sub = tf10_1.add_paragraph()
    p_sub.text = "품질, 생산성, 안전 3대 핵심 성과"
    p_sub.font.name = "맑은 고딕"
    p_sub.font.size = Pt(11)
    p_sub.font.bold = True
    p_sub.font.color.rgb = c_blue
    p_sub.space_after = Pt(16)

    bullets_s10_1 = [
        ("품질 비용 절감", "불량 유출 제로화로 연간 수억 원대 품질 배상 및 반품 손실 원천 차단"),
        ("라인 가동률 극대화", "30초 신규 온보딩 및 무중단 핫스왑으로 규격 교체 시 셧다운 90% 감축"),
        ("조업자 피로 경감", "정상품 히트맵 자동 억제 및 REWORK 구간 집중 육안 검사로 조업 생산성 증대"),
        ("품질 보증체계 확립", "MES 감사 로그 100% 무유실 기록으로 고객사 제출용 품질 보증 데이터 확보")
    ]
    for title, desc in bullets_s10_1:
        pb = tf10_1.add_paragraph()
        pb.text = f"• {title} : {desc}"
        pb.font.name = "맑은 고딕"
        pb.font.size = Pt(10.5)
        pb.font.color.rgb = c_text_dark
        pb.space_after = Pt(12)

    add_card(s10, Inches(6.833), Inches(1.6), col_w6, Inches(5.1), border_color=c_card_border, bg_color=c_card_bg)
    b10_2 = s10.shapes.add_textbox(Inches(7.133), Inches(1.9), col_w6 - Inches(0.6), Inches(4.5))
    tf10_2 = b10_2.text_frame
    tf10_2.word_wrap = True
    tf10_2.margin_left = tf10_2.margin_right = tf10_2.margin_top = tf10_2.margin_bottom = 0

    p = tf10_2.paragraphs[0]
    p.text = "100% 오프라인 망분리 완성 (Air-Gapped)"
    p.font.name = "맑은 고딕"
    p.font.size = Pt(16)
    p.font.bold = True
    p.font.color.rgb = c_primary
    p.space_after = Pt(4)

    p_sub2 = tf10_2.add_paragraph()
    p_sub2.text = "외부 연결 제로화 및 실측 검증 완료"
    p_sub2.font.name = "맑은 고딕"
    p_sub2.font.size = Pt(11)
    p_sub2.font.bold = True
    p_sub2.font.color.rgb = c_blue
    p_sub2.space_after = Pt(16)

    bullets_s10_2 = [
        ("외부 통신 제로", "네트워크 소켓 차단 상태 전수 검증 통과 (test_offline_airgap.py All Pass)"),
        ("텔레메트리 완전 제거", "외부 CDN 및 torchhub 의존성 제로화 및 로컬 단독 번들링 완성"),
        ("Master Hub HTML", "단일 파일로 모든 실측 차트와 모델을 인터랙티브하게 검증 가능한 허브 제공"),
        ("5인 팀원 역할 분리", "Role 1a/1b/2/3/4/5 전용 가이드, 검증 스크립트, 제출 ZIP 독립 패키징 완료")
    ]
    for title, desc in bullets_s10_2:
        pb = tf10_2.add_paragraph()
        pb.text = f"• {title} : {desc}"
        pb.font.name = "맑은 고딕"
        pb.font.size = Pt(10.5)
        pb.font.color.rgb = c_text_dark
        pb.space_after = Pt(12)

    # =========================================================================
    # SLIDE 11: Q&A (질의응답 및 클로징)
    # =========================================================================
    s11 = prs.slides.add_slide(blank_layout)
    add_header(s11, 10, "Q&A", "질의응답 및 심사위원 방어", 11)

    add_card(s11, Inches(1.2), Inches(1.8), Inches(10.933), Inches(4.8), border_color=RGBColor(210, 225, 245), bg_color=RGBColor(248, 250, 253))
    b11 = s11.shapes.add_textbox(Inches(1.6), Inches(2.2), Inches(10.133), Inches(4.0))
    tf11 = b11.text_frame
    tf11.word_wrap = True
    tf11.margin_left = tf11.margin_right = tf11.margin_top = tf11.margin_bottom = 0

    p = tf11.paragraphs[0]
    p.text = "경청해 주셔서 대단히 감사합니다."
    p.font.name = "맑은 고딕"
    p.font.size = Pt(28)
    p.font.bold = True
    p.font.color.rgb = c_primary
    p.space_after = Pt(8)

    p_sub = tf11.add_paragraph()
    p_sub.text = "스틸가디언 (SteelGuardian) 팀  |  발표자 : 전종현 (Role 5 총괄)"
    p_sub.font.name = "맑은 고딕"
    p_sub.font.size = Pt(14)
    p_sub.font.bold = True
    p_sub.font.color.rgb = c_blue
    p_sub.space_after = Pt(20)

    qa_items = [
        ("통합 인터랙티브 기술 허브", "docs/SteelGuardian_Master_Hub.html (단일 파일로 모든 차트/성능 확인)"),
        ("심사위원 방어 매트릭스", "docs/QA_DEFENSE_MATRIX.md (10대 핵심 예상 질문 및 반론 완비)"),
        ("SSOT 지표 총괄 문서", "docs/final_metrics.md (5-Seed 교차검증, 7대 섭동, 200건 부하 실측 데이터)"),
        ("공식 제출 산출물 패키지", "code_lightweight.zip (0 FAIL / 0 WARN 무결점 패키징 완료)")
    ]
    for title, desc in qa_items:
        pb = tf11.add_paragraph()
        pb.text = f"• {title} : {desc}"
        pb.font.name = "맑은 고딕"
        pb.font.size = Pt(11)
        pb.font.color.rgb = c_text_dark
        pb.space_after = Pt(10)

    # Save presentation
    output_path = "docs/SteelGuardian_Presentation_Deck.pptx"
    prs.save(output_path)
    print(f"Saved visual deck to {output_path}")

    # Also copy to Downloads folder
    dl_path = "C:/Users/wjswh/Downloads/SteelGuardian_Presentation_Deck.pptx"
    shutil.copy2(output_path, dl_path)
    print(f"Copied visual deck to {dl_path}")

if __name__ == '__main__':
    build_visual_deck()
