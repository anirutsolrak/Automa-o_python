#!/usr/bin/env python3
import subprocess
import time
import os
import sys

# --- CONFIGURAÇÕES ---
SERVIDOR = "10.0.0.10"
USUARIO = "svc_automacao"
SENHA = "<SENHA_SMB>"
SHARE = "Arquivos"
    
SUBPASTAS = [
    "Automacao/Atas (concluidas pela automacao)/2026/01.2026",
    "Automacao/Atas (concluidas pela automacao)/2026/02.2026",
    "Automacao/Editais/2026/01.2026",
    "Automacao/Editais/2026/02.2026"
]

# Sobe a VPN em background (mata conexões antigas antes) e aguarda ~30s ela
# estabilizar, pra os testes de SMB rodarem com a rota já ativa.
def gerenciar_vpn():
    print("=" * 60)
    print("[1] INICIANDO AUTOMAÇÃO DA VPN") 
    print("=" * 60)
    
    # 1. Garante que não existam conexões antigas travadas
    print("[*] Limpando conexões anteriores...")
    subprocess.run(['sudo', 'pkill', 'openfortivpn'], capture_output=True)
    time.sleep(2)

    # 2. Inicia o openfortivpn em segundo plano (como se fosse outro terminal)
    print("[*] Abrindo túnel VPN (em background)...")
    try:
        # Popen inicia o processo e não espera ele terminar
        subprocess.Popen(
            ['sudo', 'openfortivpn'],
            stdout=subprocess.DEVNULL, # Joga a saída fora para não sujar seu terminal
            stderr=subprocess.DEVNULL,
            start_new_session=True     # Garante que ele continue se o script fechar
        )
        
        print("[*] Aguardando 30 segundos para o túnel estabelecer...")
        # Barra de progresso simples
        for i in range(30, 0, -1):
            sys.stdout.write(f"\r    Aguardando: {i}s  ")
            sys.stdout.flush()
            time.sleep(1)
        print("\n[✓] Tempo de espera concluído.")
        
    except Exception as e:
        print(f"[ERRO] Falha ao disparar comando da VPN: {e}")
        sys.exit(1)

# Testa o acesso ao SMB de forma isolada: ping no servidor e listagem de cada
# subpasta esperada via smbclient, imprimindo o que achou (ou o erro).
def testar_diagnostico():
    print("\n" + "=" * 60)
    print("[2] INICIANDO TESTES DE ACESSO SMB")
    print("=" * 60)

    # Teste de Conectividade
    res_ping = subprocess.run(['ping', '-c', '2', '-W', '5', SERVIDOR], capture_output=True)
    if res_ping.returncode != 0:
        print(f"[ERRO] Servidor {SERVIDOR} ainda não responde ao ping.")
        print("Dica: Verifique se as credenciais no arquivo /etc/openfortivpn/config estão corretas.")
        return

    print(f"[OK] Servidor {SERVIDOR} encontrado!")

    # Teste de Listagem
    for sub in SUBPASTAS:
        print(f"\n[*] Listando: {sub}")
        cmd_ls = [
            'smbclient', f'//{SERVIDOR}/{SHARE}',
            '-U', f'{USUARIO}%{SENHA}',
            '-c', f'ls "{sub}/*"'
        ]
        
        res = subprocess.run(cmd_ls, capture_output=True, text=True)
        if res.returncode == 0:
            linhas = [l.strip() for l in res.stdout.split('\n') if len(l.strip()) > 15]
            if linhas:
                for item in linhas[:5]: print(f"    - {item}")
            else:
                print("    (Pasta vazia)")
        else:
            print(f"    [X] Falha no acesso: {res.stderr.strip()}")

# Ciclo completo do diagnóstico: sobe a VPN e roda os testes de SMB.
def main():
    gerenciar_vpn()
    testar_diagnostico()
    
    print("\n" + "=" * 60)
    print("PROCESSO CONCLUÍDO")
    print("A VPN continuará rodando em background.")
    print("Para desligar use: sudo pkill openfortivpn")
    print("=" * 60)

if __name__ == "__main__":
    main()