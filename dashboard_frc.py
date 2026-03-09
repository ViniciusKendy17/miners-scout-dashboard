import streamlit as st
# import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import io
import plotly.graph_objects as go



# Page configuration
st.set_page_config(
    page_title="FRC REEFSCAPE Dashboard",
    page_icon="🤖",
    layout="wide"
)


# Point mapping
POINTS_MAP = {
    'LEAVE': {'auto': 3, 'teleop': 0},
    'L1': {'auto': 3, 'teleop': 2},      # CORAL L1
    'L2': {'auto': 4, 'teleop': 3},      # CORAL L2
    'L3': {'auto': 6, 'teleop': 4},      # CORAL L3
    'L4': {'auto': 7, 'teleop': 5},      # CORAL L4
    'PROCESSOR': {'auto': 6, 'teleop': 6},
    'NET': {'auto': 4, 'teleop': 4},
    'PARK': {'auto': 0, 'teleop': 2},
    'SHALLOW_CAGE': {'auto': 6, 'teleop': 6},
    'DEEP_CAGE': {'auto': 12, 'teleop': 12}
}


def conectar_ao_banco():

    return st.connection("postgresql", type="sql")

@st.cache_data(ttl=15)  # Increase cache time to 10 minutes
def carregar_dados():
    conn = conectar_ao_banco()

    query = """
        SELECT 
        r.team,
        AVG(s.reliability) as reliability,
        AVG(s.scoring_capacity) as scoring_capacity,
        AVG(s.speed) as speed,
        AVG(s.defense) as defense,
        AVG(s.auto_efficiency) as auto_efficiency,
         BOOL_OR(s.ramp) as ramp_rate
        FROM robot_match_scout_tb s
        JOIN robots_tb r ON s.robot_id = r.id
        GROUP BY r.team
        """

    # Load data into DataFrame
    df = conn.query(query)

    return df
    
# Add this helper function for CSV export
def convert_df_to_csv(df):
    """Converts a DataFrame to a CSV string for download."""
    csv_buffer = io.StringIO()
    df.to_csv(csv_buffer, index=False)
    return csv_buffer.getvalue()

def main():
    st.title("🤖 FRC REBUILD Dashboard")

# Load data
    with st.spinner("Carregando dados..."):
        df = carregar_dados()

    # Criar score geral
    with st.spinner("Calculando ranking técnico..."):
        df["overall_score"] = (
            df["reliability"] * 0.25 +
            df["scoring_capacity"] * 0.25 +
            df["speed"] * 0.15 +
            df["defense"] * 0.15 +
            df["auto_efficiency"] * 0.15 +
            df["ramp_rate"] 
        )

        df = df.sort_values("overall_score", ascending=False)
        df["rank"] = range(1, len(df) + 1)


        tabs = [
                "📊 Ranking Técnico",
                "🏆 Desafios",
                "🤖 Alianças",
                "🔍 Estatísticas de Robôs"
        ]

        selected_tab = st.radio(
                "Navegação",
                tabs,
                horizontal=True,
                label_visibility="collapsed"
        )

    if selected_tab == "📊 Ranking Técnico":
        st.header("📊 Ranking Técnico das Equipes")

        # ===== CARDS SUPERIORES =====
        col1, col2 = st.columns(2)

        col1.metric("🥇 Melhor Robô", df.iloc[0]["team"])
        col2.metric("Pontuador", df.sort_values("scoring_capacity", ascending=False).iloc[0]["team"])
        
        col3, col4 = st.columns(2)
        col3.metric("Melhor Defesa", df.sort_values("defense", ascending=False).iloc[0]["team"])
        col4.metric("Melhor Auto", df.sort_values("auto_efficiency", ascending=False).iloc[0]["team"])

        st.divider()

        # ===== TABELA =====
        display_df = df.copy()

        display_df = display_df.rename(columns={
            "team": "Equipe",
            "reliability": "Confiabilidade",
            "scoring_capacity": "Capacidade de Pontuar",
            "speed": "Velocidade",
            "defense": "Defesa",
            "auto_efficiency": "Autônomo",
            "ramp_rate": "Rampa",
            "overall_score": "Score Geral",
            "rank": "Classificação"
        })

        st.dataframe(
            display_df[[
                "Classificação",
                "Equipe",
                "Score Geral",
                "Confiabilidade",
                "Capacidade de Pontuar",
                "Velocidade",
                "Defesa",
                "Autônomo",
                "Rampa"
            ]],
            use_container_width=True
        )
        
        st.download_button(
                label="📥 Exportar Classificação (CSV)",
                data=convert_df_to_csv(display_df),
                file_name="frc_rankings.csv",
                mime="text/csv",
            )

        # ===== TOP 10 =====
        st.subheader("🏆 Top 10 Equipes (Score Geral)")

        fig = px.bar(
            df.head(10).sort_values("overall_score"),
            y="team",
            x="overall_score",
            orientation="h",
            title="Top 10 por Score Técnico",
            labels={"team": "Equipe", "overall_score": "Score Geral"}
        )

        st.plotly_chart(fig, use_container_width=True)
        
    if selected_tab == "🏆 Desafios":
            
            st.header("🏆 Análise por Desafio Técnico")

            desafio = st.selectbox(
            "Selecione o tipo de desafio:",
            {
                "Velocidade": "speed",
                "Defesa": "defense",
                "Autônomo": "auto_efficiency",
                # "Rampa": "ramp_rate",
                "Pontuação": "scoring_capacity",
                "Confiabilidade": "reliability"
            }
        )

            metric_column = {
            "Velocidade": "speed",
            "Defesa": "defense",
            "Autônomo": "auto_efficiency",
            # "Rampa": "ramp_rate",
            "Pontuação": "scoring_capacity",
            "Confiabilidade": "reliability"
        }[desafio]

        # Ranking baseado na métrica escolhida
            ranking = df.sort_values(metric_column, ascending=False).reset_index(drop=True)
            ranking["rank"] = ranking[metric_column].rank(ascending=False, method="min").astype(int)

            st.subheader(f"Classificação - {desafio}")

            display_df = ranking[["rank", "team", metric_column]].rename(columns={
            "rank": "Classificação",
            "team": "Equipe",
            metric_column: "Valor"
        })

            st.dataframe(display_df, use_container_width=True)
            st.subheader("Top 5 Equipes")

            top5 = ranking.head(5)

            fig = px.bar(
                top5.sort_values(metric_column),
                x=metric_column,
                y="team",
                orientation="h",
                title=f"Top 5 - {desafio}",
                labels={"team": "Equipe", metric_column: "Valor"}
            )

            st.plotly_chart(fig, use_container_width=True)
            
            st.subheader("Comparativo Completo - Top 3")


            top3 = ranking.head(3)
            

            metric_cols = [
            "reliability",
            "scoring_capacity",
            "speed",
            "defense",
            "auto_efficiency",
            "ramp_rate"
            ]

            metric_labels = [
            "Confiabilidade",
            "Capacidade de Pontuar",
            "Velocidade",
            "Defesa",
            "Autônomo",
            "Rampa"
            ]

            radar_fig = go.Figure()

            for _, row in top3.iterrows():
                radar_fig.add_trace(go.Scatterpolar(
                    r=[row[c] for c in metric_cols],
                    theta=metric_labels,
                    fill='toself',
                    name=row["team"]
                ))

            radar_fig.update_layout(
                polar=dict(radialaxis=dict(visible=True)),
                showlegend=True,
                title="Perfil Técnico Comparativo"
            )

            st.plotly_chart(radar_fig, use_container_width=True)
                
    if selected_tab == "🤖 Alianças":
            
            st.header("Alianças Sugeridas")
            
            # Alliance configuration - removed slider and fixed alliance size to 3
            st.subheader("Configurar Alianças")
            alliance_size = 3  # Fixed alliance size
            
            # Set MINERSKILLS as default selected team with flexible matching            
            
            team_options = [""] + list(df['team'])
            
            
            # Find any team containing "MINERSKILLS" or "10019"
            default_index = 0  # Default to empty string if team not found
            for i, team in enumerate(team_options):
                if "MINERSKILLS" in team.upper() or "10019" in team:
                    default_index = i
                    break
                        
            selected_team = st.selectbox(
                "Selecione uma equipe:",
                options=team_options,
                index=default_index
            )
            
            # ==============================
            # DEFINIR ATRIBUTOS PRINCIPAIS
            # ==============================

            main_attributes = ['scoring_capacity', 'defense', 'auto_efficiency']

            team_profile = df[df["team"] == selected_team][main_attributes].iloc[0]

            # Descobrir qual é o papel principal do robô selecionado
            primary_role = team_profile.idxmax()

            # Descobrir quais papéis faltam na aliança
            needed_roles = list(set(main_attributes) - {primary_role})

            # ==============================
            # CONSTRUÇÃO DA ALIANÇA
            # ==============================

            alliance = [selected_team]

            # Para cada papel necessário, buscar o melhor robô disponível
            for role in needed_roles:
                
                best_candidate = df[
                    ~df["team"].isin(alliance)
                ].sort_values(by=role, ascending=False)
                
                if not best_candidate.empty:
                    alliance.append(best_candidate.iloc[0]["team"])

            # Garantir que temos 3 equipes
            alliance = alliance[:alliance_size]
            
            st.subheader(f"Aliança Estratégica com {selected_team}")

            team_cols = st.columns(len(alliance))

            for j, team in enumerate(alliance):
                with team_cols[j]:
                    team_data = df[df["team"] == team].iloc[0]
                    
                    role_attr = team_data[main_attributes].idxmax()
                    
                    if role_attr == "scoring_capacity":
                        role_name = "Scorer"
                    elif role_attr == "defense":
                        role_name = "Defender"
                    else:
                        role_name = "Auto Specialist"

                    st.metric(
                        f"Equipe {j+1}",
                        team,
                        role_name
                    )

                    st.markdown(f"""
                    **Scoring:** {team_data['scoring_capacity']:.2f}  
                    **Defense:** {team_data['defense']:.2f}  
                    **Auto:** {team_data['auto_efficiency']:.2f}
                    """)
                    
                    
    if selected_tab == "🔍 Estatísticas de Robôs":
        st.header("🤖 Perfil do Robô")

        robots = sorted(df["team"].unique())
        selected_robot = st.selectbox("Selecione um robô:", robots)

        if selected_robot:
            robot_data = df[df["team"] == selected_robot].iloc[0]

            st.subheader(f"Equipe {selected_robot}")

            col1, col2, col3 = st.columns(3)

            with col1:
                st.metric("Classificação Geral", f"{int(robot_data['rank'])}º")

            with col2:
                st.metric("Score Geral", f"{robot_data['overall_score']:.2f}")
            
            st.subheader("Comparar Robôs")

            selected_robots = st.multiselect(
                "Selecione robôs para comparar:",
                robots
            )

            if selected_robots:
                compare_data = df[df["team"].isin(selected_robots)]

                # Radar comparativo
                radar_fig = go.Figure()

                metric_cols = [
                    "reliability",
                    "scoring_capacity",
                    "speed",
                    "defense",
                    "auto_efficiency",
                    "ramp_rate"
                ]

                metric_labels = [
                    "Confiabilidade",
                    "Capacidade de Pontuar",
                    "Velocidade",
                    "Defesa",
                    "Autônomo",
                    "Rampa"
                ]


                for _, row in compare_data.iterrows():
                    radar_fig.add_trace(go.Scatterpolar(
                        r=[row[col] for col in metric_cols],
                        theta=metric_labels,
                        fill='toself',
                        name=row["team"]
                    ))

                radar_fig.update_layout(
                    polar=dict(radialaxis=dict(visible=True)),
                    title="Comparação Técnica",
                    showlegend=True
                )

                st.plotly_chart(radar_fig, use_container_width=True)

if __name__ == "__main__":
    main()