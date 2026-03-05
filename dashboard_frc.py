import streamlit as st
import pandas as pd
import psycopg2 as pg
import plotly.express as px
import plotly.graph_objects as go
import io
import time
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

    return pg.connect(
        host=st.secrets["DB_HOST"],
        user=st.secrets["DB_USER"],
        password=st.secrets["DB_PASSWORD"],
        database=st.secrets["DB_NAME"],
        port= st.secrets["DB_PORT"]
    )

@st.cache_data(ttl=600)  # Increase cache time to 10 minutes
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
        AVG(CASE WHEN s.ramp THEN 1 ELSE 0 END) as ramp_rate
        FROM robot_match_scout_tb s
        JOIN robots_tb r ON s.robot_id = r.id
        GROUP BY r.team
        """

    # Load data into DataFrame
    df = pd.read_sql_query(query, conn)
    conn.close()
    
    return df
    
@st.cache_data(ttl=600)    
def carregarClimb_dados():
    conn = conectar_ao_banco()
    
    query = ""
    
    df = pd.read_sql_query(query, conn)
    
    conn.close()
    
    return df
    

@st.cache_data(ttl=600)
def processar_dados(df):
    # Transform phase_name to match POINTS_MAP keys if needed
    phase_mapping = {
        'CORAL L1': 'L1',
        'CORAL L2': 'L2',
        'CORAL L3': 'L3',
        'CORAL L4': 'L4',
        'BARGE': 'PARK'
        # Add other mappings if necessary
    }
    df['phase_key'] = df['phase_name'].map(phase_mapping).fillna(df['phase_name'])
    
    # Calculate points - first create empty columns
    df['auto_points'] = 0.0
    df['teleop_points'] = 0.0
    
    # Vectorize operations where possible instead of looping
    for phase, points in POINTS_MAP.items():
        mask = df['phase_key'] == phase
        df.loc[mask, 'auto_points'] = df.loc[mask, 'completed_autonomous'] * points['auto']
        df.loc[mask, 'teleop_points'] = df.loc[mask, 'completed_teleop'] * points['teleop']
    
    # Calculate total points
    df['total_points'] = df['auto_points'] + df['teleop_points']
    
    return df

@st.cache_data(ttl=600)
def calcular_rankings(df):
    # Calculate team rankings
    team_rankings = df.groupby('team').agg({
        'auto_points': 'sum',
        'teleop_points': 'sum',
        'total_points': 'sum'
    }).reset_index()
    
    team_rankings['rank'] = team_rankings['total_points'].rank(ascending=False, method='min').astype(int)
    team_rankings = team_rankings.sort_values('rank')
    
    # Calculate challenge-specific rankings
    challenge_rankings = df.groupby(['team', 'challenge_name']).agg({
        'auto_points': 'sum',
        'teleop_points': 'sum', 
        'total_points': 'sum'
    }).reset_index()
    
    return team_rankings, challenge_rankings

@st.cache_data(ttl=600)
def construir_alianca_otima(team_rankings, challenge_rankings, df_processed, tamanho_alianca=3, max_teams=30):
    """Optimized alliance builder that considers phase-specific performance within challenges"""
    start_time = time.time()
    
    # Limit to top teams for better performance
    top_teams = team_rankings.sort_values('total_points', ascending=False).head(max_teams)['team'].tolist()
    available_teams = set(top_teams)
    
    aliances = []
    
    # Create phase-level performance data with challenge context
    phase_performance = df_processed[df_processed['team'].isin(top_teams)].groupby(
        ['team', 'challenge_name', 'phase_name']
    ).agg({
        'total_points': 'sum',
        'completed_autonomous': 'sum',
        'completed_teleop': 'sum'
    }).reset_index()
    
    # Create a dictionary to store best phases for each team in each challenge
    team_challenge_phases = {}
    for team in top_teams:
        team_data = phase_performance[phase_performance['team'] == team]
        team_challenge_phases[team] = {}
        
        # Group by challenge to find best phases within each challenge
        for challenge in team_data['challenge_name'].unique():
            challenge_phases = team_data[team_data['challenge_name'] == challenge]
            # Sort phases by total points to get best performing phases
            best_phases = challenge_phases.sort_values('total_points', ascending=False)
            team_challenge_phases[team][challenge] = {
                'phases': [
                    {
                        'name': row['phase_name'],
                        'points': row['total_points'],
                        'completions': row['completed_autonomous'] + row['completed_teleop']
                    }
                    for _, row in best_phases.iterrows()
                ]
            }
    
    def calculate_alliance_synergy(current_alliance, candidate):
        """Calculate how well a candidate complements the current alliance based on phase-specific strengths"""
        if not current_alliance:
            # For first team, consider their overall phase coverage
            candidate_phases = team_challenge_phases[candidate]
            total_score = 0
            for challenge, data in candidate_phases.items():
                if data['phases']:
                    # Consider their best phase in each challenge
                    total_score += max(phase['points'] for phase in data['phases'])
            return total_score
        
        # Get current alliance's best phases for each challenge
        alliance_coverage = {}
        for team in current_alliance:
            team_phases = team_challenge_phases[team]
            for challenge, data in team_phases.items():
                if challenge not in alliance_coverage:
                    alliance_coverage[challenge] = {'covered_phases': set(), 'max_points': {}}
                
                for phase in data['phases']:
                    phase_name = phase['name']
                    alliance_coverage[challenge]['covered_phases'].add(phase_name)
                    current_max = alliance_coverage[challenge]['max_points'].get(phase_name, 0)
                    alliance_coverage[challenge]['max_points'][phase_name] = max(current_max, phase['points'])
        
        # Calculate how well candidate complements the alliance
        synergy_score = 0
        candidate_phases = team_challenge_phases[candidate]
        
        for challenge, data in candidate_phases.items():
            if not data['phases']:
                continue
                
            # Check each phase the candidate is good at
            for phase in data['phases']:
                phase_name = phase['name']
                phase_points = phase['points']
                
                if challenge not in alliance_coverage:
                    # Candidate brings entirely new challenge capability
                    synergy_score += phase_points * 1.5  # Bonus for new challenge coverage
                elif phase_name not in alliance_coverage[challenge]['covered_phases']:
                    # Candidate brings new phase capability
                    synergy_score += phase_points * 1.2  # Bonus for new phase coverage
                else:
                    # Check if candidate significantly improves existing phase coverage
                    current_max = alliance_coverage[challenge]['max_points'].get(phase_name, 0)
                    if phase_points > current_max:
                        synergy_score += (phase_points - current_max)  # Value of improvement
        
        return synergy_score
    
    # Build alliances with improved phase-specific synergy calculation
    for seed_team in top_teams[:10]:  # Use top 10 teams as seeds
        if seed_team not in available_teams:
            continue
        
        alliance = [seed_team]
        available_teams.remove(seed_team)
        
        # Find complementary teams based on phase-specific strengths
        while len(alliance) < tamanho_alianca and available_teams:
            best_synergy = -1
            best_team = None
            
            for candidate in available_teams:
                synergy = calculate_alliance_synergy(alliance, candidate)
                if synergy > best_synergy:
                    best_synergy = synergy
                    best_team = candidate
            
            if best_team:
                alliance.append(best_team)
                available_teams.remove(best_team)
            else:
                break
        
        # Calculate alliance metrics
        alliance_total_points = sum(team_rankings[team_rankings['team'].isin(alliance)]['total_points'])
        
        # Calculate phase coverage for visualization
        alliance_phase_coverage = phase_performance[
            phase_performance['team'].isin(alliance)
        ].groupby(['challenge_name', 'phase_name']).agg({
            'total_points': 'sum'
        }).reset_index()
        
        # Calculate balance score based on phase coverage
        phase_balance = alliance_phase_coverage['total_points'].std() / alliance_phase_coverage['total_points'].mean() if len(alliance_phase_coverage) > 0 else 1
        
        aliances.append({
            'teams': alliance,
            'total_points': alliance_total_points,
            'balance_score': 1 / (1 + phase_balance),  # Higher is better
            'phase_coverage': alliance_phase_coverage
        })
    
    # Sort alliances by a combination of total points and phase balance
    aliances.sort(key=lambda x: (x['total_points'] * x['balance_score']), reverse=True)
    
    print(f"Alliance builder ran in {time.time() - start_time:.2f} seconds")
    
    return aliances

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
        # df = processar_dados(df)

    # Criar score geral
    with st.spinner("Calculando ranking técnico..."):
        df["overall_score"] = (
            df["reliability"] * 0.25 +
            df["scoring_capacity"] * 0.25 +
            df["speed"] * 0.15 +
            df["defense"] * 0.15 +
            df["auto_efficiency"] * 0.15 +
            df["ramp_rate"] * 0
        )

        df = df.sort_values("overall_score", ascending=False)
        df["rank"] = range(1, len(df) + 1)

    tab1, tab2, tab3, tab4 = st.tabs(
        ["📊 Ranking Técnico", "🏆 Desafios", "🤖 Alianças", "🔍 Estatísticas de Robôs"]
    )

    with tab1:
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
        
    with tab2:
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
                
    with tab3:
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
                        role_name = "🔥 Scorer"
                    elif role_attr == "defense":
                        role_name = "🛡 Defender"
                    else:
                        role_name = "🤖 Auto Specialist"

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
                    
                    
                    
            st.subheader("Recomendação Estratégica")

            if primary_role == "defense":
                explanation = "Como o robô selecionado atua principalmente como Defensor, foram adicionados um Scorer forte e um especialista em Autônomo para equilibrar a aliança."
            elif primary_role == "scoring_capacity":
                explanation = "Como o robô selecionado é o principal Scorer, foram adicionados um Defensor forte e um especialista em Autônomo para balancear a composição."
            else:
                explanation = "Como o robô selecionado é forte no Autônomo, foram adicionados um Scorer e um Defensor para complementar a estratégia."

            st.markdown(explanation)
            
            
            # # Only do expensive calculations if a team is selected
            # if selected_team:
            #     with st.spinner("Calculando alianças otimizadas..."):
                    
                        
            #         # Get team's challenge performance
            #         team_challenge_points = df[df["team"] == selected_team][['reliability', 'scoring_capacity', 'speed', 'defense', 'auto_efficiency']].mean()

            #         # Simpler version - just get best/worst challenges without phase detail
            #         best_challenges = team_challenge_points[team_challenge_points > 3].head(2)
            #         worst_challenges = team_challenge_points[team_challenge_points <= 3].head(2)
                    

            #         st.write("### Perfil de Desempenho")
            #         cols = st.columns(2)
            #         with cols[0]:
            #             st.write("**Pontos Fortes:**")
            #             for note, value in best_challenges.items():
            #                  st.write(f"🔥 {note}: {value:.2f}")
                    
            #         with cols[1]:
            #             st.write("**Pontos Fracos:**")
            #             for note, value in worst_challenges.items():
            #                  st.write(f"🔥 {note}: {value:.2f}")
                                                
            #         # Simplified alliance building logic
            #         # Start with the selected team
            #         alliance = [selected_team]
                    
            #         # For each weak challenge, find a strong team
            #         for _, challenge_row in worst_challenges.iterrows():
            #             if len(alliance) >= alliance_size:
            #                 break
                            
            #             challenge = challenge_row['challenge_name']
                        
            #             # Find strong teams in this challenge
            #             strong_teams = challenge_rankings[
            #                 (challenge_rankings['challenge_name'] == challenge) & 
            #                 ~(challenge_rankings['team'].isin(alliance))
            #             ].sort_values('total_points', ascending=False).head(5)  # Limit to top 5
                        
            #             if not strong_teams.empty:
            #                 best_team = strong_teams.iloc[0]['team']
            #                 alliance.append(best_team)
                    
            #         # If alliance still not complete, add highest scoring available teams
            #         while len(alliance) < alliance_size:
            #             remaining = team_rankings[
            #                 ~team_rankings['team'].isin(alliance)
            #             ].sort_values('total_points', ascending=False).head(5)  # Limit to top 5
                        
            #             if remaining.empty:
            #                 break
                            
            #             alliance.append(remaining.iloc[0]['team'])
                    
            #         # Calculate alliance total points
            #         alliance_points = team_rankings[team_rankings['team'].isin(alliance)]['total_points'].sum()
                    
            #         st.subheader(f"Aliança Complementar com {selected_team}")
                    
            #         # Show teams in horizontal columns
            #         team_cols = st.columns(len(alliance))
            #         for j, team in enumerate(alliance):
            #             with team_cols[j]:
            #                 team_data = team_rankings[team_rankings['team'] == team].iloc[0]
                            
            #                 # Display team name and rank
            #                 st.metric(
            #                     f"Equipe {j+1}", 
            #                     team, 
            #                     f"Rank: {int(team_data['rank'])}"
            #                 )
                            
            #                 # Get team's best challenge and phases
            #                 team_phases = df[df['team'] == team].groupby(
            #                     ['challenge_name', 'phase_name']
            #                 ).agg({
            #                     'total_points': 'sum'
            #                 }).reset_index()
                            
            #                 if not team_phases.empty:
            #                     # Group by challenge first to find best challenge
            #                     challenge_totals = team_phases.groupby('challenge_name')['total_points'].sum().reset_index()
            #                     best_challenge = challenge_totals.loc[challenge_totals['total_points'].idxmax()]
                                
            #                     # Find best phase within best challenge
            #                     best_phase = team_phases[
            #                         team_phases['challenge_name'] == best_challenge['challenge_name']
            #                     ].sort_values('total_points', ascending=False).iloc[0]
                                
            #                     st.markdown(f"""
            #                     **Melhor Desafio:** {best_challenge['challenge_name']}
            #                     - *Melhor Fase:* {best_phase['phase_name']}
            #                     - *Pontos:* {int(best_phase['total_points'])}
            #                     """)
                    
            #         # Show total alliance points
            #         st.metric("Pontuação Total da Aliança", f"{int(alliance_points)} pontos")
                    
            #         # Simplified challenge coverage visualization
            #         st.subheader("Cobertura de Desafios da Aliança")
            #         alliance_by_challenge = challenge_rankings[
            #             challenge_rankings['team'].isin(alliance)
            #         ].groupby('challenge_name').agg({
            #             'total_points': 'sum'
            #         }).reset_index()
                    
            #         # Use simpler bar chart instead of radar chart
            #         fig = px.bar(
            #             alliance_by_challenge.sort_values('total_points', ascending=False),
            #             x='challenge_name',
            #             y='total_points',
            #             title="Pontuação por Desafio",
            #             labels={'challenge_name': 'Desafio', 'total_points': 'Pontos Totais'}
            #         )
            #         st.plotly_chart(fig, use_container_width=True)
            
            # else:
            #     # Show a maximum of 3 pre-computed alliances to avoid performance issues
            #     with st.spinner("Calculando melhores alianças..."):
            #         alliances = construir_alianca_otima(team_rankings, challenge_rankings, df, alliance_size, max_teams=20)
                    
            #         st.subheader(f"Melhores Alianças Complementares (Tamanho: {alliance_size})")
                    
            #         # Only show top 3 alliances
            #         for i, alliance in enumerate(alliances[:3]):
            #             st.markdown(f"### Aliança {i+1} - {int(alliance['total_points'])} pontos")
                        
            #             # Show teams in horizontal columns
            #             team_cols = st.columns(len(alliance['teams']))
            #             for j, team in enumerate(alliance['teams']):
            #                 with team_cols[j]:
            #                     team_data = team_rankings[team_rankings['team'] == team].iloc[0]
                                
            #                     # Display team name and rank
            #                     st.metric(
            #                         f"Equipe {j+1}", 
            #                         team, 
            #                         f"Rank: {int(team_data['rank'])}"
            #                     )
                                
            #                     # Get team's best challenge and phases
            #                     team_phases = df[df['team'] == team].groupby(
            #                         ['challenge_name', 'phase_name']
            #                     ).agg({
            #                         'total_points': 'sum'
            #                     }).reset_index()
                                
            #                     if not team_phases.empty:
            #                         # Group by challenge first to find best challenge
            #                         challenge_totals = team_phases.groupby('challenge_name')['total_points'].sum().reset_index()
            #                         best_challenge = challenge_totals.loc[challenge_totals['total_points'].idxmax()]
                                    
            #                         # Find best phase within best challenge
            #                         best_phase = team_phases[
            #                             team_phases['challenge_name'] == best_challenge['challenge_name']
            #                         ].sort_values('total_points', ascending=False).iloc[0]
                                    
            #                         st.markdown(f"""
            #                         **Melhor Desafio:** {best_challenge['challenge_name']}
            #                         - *Melhor Fase:* {best_phase['phase_name']}
            #                         - *Pontos:* {int(best_phase['total_points'])}
            #                         """)
                        
            #             # Show phase coverage visualization
            #             if 'phase_coverage' in alliance and not alliance['phase_coverage'].empty:
            #                 st.subheader("Cobertura de Fases da Aliança")
                            
            #                 # Create a more detailed visualization showing phases within challenges
            #                 coverage_data = alliance['phase_coverage'].sort_values(['challenge_name', 'total_points'], ascending=[True, False])
                            
            #                 fig = px.bar(
            #                     coverage_data,
            #                     x='phase_name',
            #                     y='total_points',
            #                     color='challenge_name',
            #                     title="Pontuação por Fase em cada Desafio",
            #                     labels={
            #                         'phase_name': 'Fase',
            #                         'total_points': 'Pontos Totais',
            #                         'challenge_name': 'Desafio'
            #                     },
            #                     barmode='group'
            #                 )
                            
            #                 fig.update_layout(
            #                     xaxis_title="Fases",
            #                     yaxis_title="Pontos",
            #                     legend_title="Desafios"
            #                 )
                            
            #                 st.plotly_chart(fig, use_container_width=True)
                        
            #                 st.markdown("---")  # Add a separator between alliances
        
    with tab4:        
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

            with col3:
                st.metric("Confiabilidade", f"{robot_data['reliability']:.2f}")
                
            
            st.subheader("Comparar Robôs")

            selected_robots = st.multiselect(
                "Selecione robôs para comparar:",
                robots
            )

            if selected_robots:
                compare_data = df[df["team"].isin(selected_robots)]

                # Radar comparativo
                radar_fig = go.Figure()

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