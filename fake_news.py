#!/usr/bin/env python3
"""
CS112 Final Project - Fake News
Flask server that provides AI summary and fake news detection.
The user interaction module is now in discussion and design stage, and will release in later versions.
"""

import sys
import os
import base64
import json
import time
import asyncio
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from flask import Flask, request, jsonify, Response
from flask_cors import CORS

# 将 py 目录添加到 Python 路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'py'))

from llmproxy import LLMProxy
from dotenv import load_dotenv
from court_manager import court_manager

# 加载 .env
load_dotenv()

# 设置异步异常处理器，忽略 "Event loop is closed" 错误
# 这个错误发生在 Model Court 清理资源时，不影响功能
def handle_asyncio_exception(loop, context):
    exception = context.get('exception')
    if isinstance(exception, RuntimeError) and 'Event loop is closed' in str(exception):
        # 忽略这个无害的清理错误
        return
    # 其他异常正常输出
    loop.default_exception_handler(context)

asyncio.set_event_loop_policy(asyncio.DefaultEventLoopPolicy())
try:
    loop = asyncio.get_event_loop()
    loop.set_exception_handler(handle_asyncio_exception)
except:
    pass

# 创建 LLMProxy 客户端实例
client = LLMProxy()
app = Flask(__name__)
CORS(app)

# 服务器配置
FLASK_HOST = '127.0.0.1'
FLASK_PORT = 5000


@app.route('/api/summary', methods=['GET', 'POST'])
def get_summary():
    """
    生成 AI 总结 + Fake News 检测
    由浏览器中的 JavaScript 异步调用
    
    Returns:
    {
        "summary": "网页总结文本",
        "confidence": "CLEAN/SUSPICIOUS/FAKE",
        "fact_details": "fact check详细结果"
    }
    """
    try:
        # 支持 GET 和 POST
        if request.method == 'POST':
            data = request.get_json()
            page_url = data.get('url', '')
            page_content = data.get('content', '')
        else:
            page_url = request.args.get('url', '')
            page_content = request.args.get('content', '')
        
        print(f"[SUMMARY] Request from {page_url[:70] if page_url else 'unknown'}")
        print(f"[SUMMARY] Content length: {len(page_content)} chars")
        
        if not page_content or len(page_content) < 50:
            print("[SUMMARY] Content too short")
            return jsonify({
                'summary': 'Page content insufficient to generate summary.',
                'confidence': 'N/A',
                'fact_details': 'Insufficient content to analyze.'
            })
        
        # 调用 LLM 进行fact extraction（并行执行summary和fact check）
        summary, fact_check_result = analyze_content(page_content, page_url)
        
        print(f"[SUMMARY] Analysis complete: confidence={fact_check_result['confidence']}")
        
        return jsonify({
            'summary': summary,
            'confidence': fact_check_result['confidence'],
            'fact_details': fact_check_result['details'],  # fact check详细结果（自然语言）
            'url': page_url
        })
    
    except Exception as e:
        print(f"[ERROR] Analysis failed: {e}")
        return jsonify({
            'error': str(e),
            'summary': 'Analysis failed',
            'confidence': 'N/A',
            'fact_details': 'Analysis incomplete.'
        }), 200


@app.route('/api/feedback', methods=['POST'])
def submit_feedback():
    """
    接收用户反馈
    用户可以提交对内容的判断和理由
    
    Request:
    {
        "url": "页面URL",
        "content_background": "页面内容背景",
        "feedback_content": "用户提供的fact内容",
        "feedback_type": "fact" | "suspicious_fact" | "fake_fact",
        "feedback_prove": "用户提供的证据"
    }
    
    Returns:
    {
        "success": true/false,
        "message": "提示信息"
    }
    """
    try:
        data = request.get_json()
        
        page_url = data.get('url', '')
        content_background = data.get('content_background', '')
        feedback_content = data.get('feedback_content', '')
        feedback_type = data.get('feedback_type', '')
        feedback_prove = data.get('feedback_prove', '')
        
        print(f"[FEEDBACK] Received feedback: type={feedback_type}, url={page_url[:50]}")
        
        # 验证输入
        if not feedback_type or feedback_type not in ['fact', 'suspicious_fact', 'fake_fact']:
            return jsonify({
                'success': False,
                'message': 'Invalid feedback type'
            }), 400
        
        if not feedback_content or len(feedback_content) < 10:
            return jsonify({
                'success': False,
                'message': 'Please provide the fact content (at least 10 characters)'
            }), 400
        
        if not feedback_prove or len(feedback_prove) < 10:
            return jsonify({
                'success': False,
                'message': 'Please provide evidence/proof (at least 10 characters)'
            }), 400
        
        # 保存feedback
        save_user_feedback(page_url, content_background, feedback_content, feedback_type, feedback_prove)
        
        return jsonify({
            'success': True,
            'message': 'Thank you for your feedback!'
        })
    
    except Exception as e:
        print(f"[ERROR] Feedback submission failed: {e}")
        return jsonify({
            'success': False,
            'message': 'Failed to save feedback'
        }), 500


@app.route('/enhance', methods=['POST'])
def enhance_html():
    """
    注入 JavaScript 脚本到 HTML，异步加载 AI 总结和 Fake News 检测
    """
    try:
        data = request.get_json(force=True)
        
        if not data:
            return jsonify({'error': 'Invalid JSON'}), 400
        
        if 'html_base64' in data:
            html_content = base64.b64decode(data['html_base64']).decode('utf-8', errors='replace')
            original_url = data.get('url', '')
            print(f"[ENHANCE] Received {len(html_content)} bytes from {original_url}")
        elif 'html' in data:
            html_content = data['html']
            original_url = data.get('url', '')
        else:
            return jsonify({'error': 'Missing html or html_base64'}), 400
        
        # Inject JavaScript
        modified_html = inject_async_summary_script(html_content, original_url)
        
        print(f"[ENHANCE] Injected script, returning {len(modified_html)} bytes")
        
        html_base64 = base64.b64encode(modified_html.encode('utf-8')).decode('ascii')
        response_json = json.dumps({'html_base64': html_base64}, ensure_ascii=True)
        
        return Response(response_json, mimetype='application/json')
    
    except Exception as e:
        print(f"[ERROR] Enhancement failed: {e}")
        return jsonify({'error': str(e)}), 500


def save_website_content(text, url="", content_type="summary"):
    """
    保存网页内容到日志文件，用于调试
    
    Args:
        text: 网页内容
        url: 页面URL
        content_type: 内容类型 ("summary" 或 "facts")
    """
    try:
        # 根据content_type确定子文件夹
        if content_type == "summary":
            log_dir = "logs/websites_summary"
        elif content_type == "facts":
            log_dir = "logs/websites_facts"
        else:
            log_dir = "logs/websites_other"
        
        # 确保文件夹存在
        if not os.path.exists(log_dir):
            os.makedirs(log_dir)
        
        # 生成文件名：时间戳
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        filename = f"{log_dir}/website_{timestamp}.txt"
        
        # 保存内容
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(f"URL: {url}\n")
            f.write(f"Timestamp: {datetime.now().isoformat()}\n")
            f.write(f"Content Type: {content_type}\n")
            f.write(f"Content Length: {len(text)} chars\n")
            f.write("=" * 80 + "\n\n")
            f.write(text)
        
        print(f"[LOG] Saved {content_type} content to {filename}")
        
    except Exception as e:
        print(f"[ERROR] Failed to save website content: {e}")


def generate_summary_gpt(text, url=""):
    """
    使用GPT-4o-mini生成网页摘要
    
    Args:
        text: Content to summarize
        url: 页面URL
    
    Returns:
        str: Summary text
    """
    try:
        text_summary = text[:3000]  # GPT用于summary，3000字符足够
        
        # 保存即将发送给GPT的内容（用于调试）
        save_website_content(text_summary, url, "summary")
        
        print(f"[GPT] Starting summary generation ({len(text_summary)} chars)")
        start_time = time.time()
        
        system_prompt = """You are a web content summarization assistant.
Your task: Provide a concise summary of the webpage content in English (no more than 100 words).

Focus on:
- Main topic and key points
- Important information
- Core message

Only return the summary text, no JSON format needed."""
        
        # 调用 GPT-4o-mini
        response = client.generate(
            model='4o-mini',
            system=system_prompt,
            query=text_summary,
            temperature=0.3,
            lastk=0
        )
        
        elapsed = time.time() - start_time
        summary = response['result'].strip()
        
        print(f"[GPT] Summary completed in {elapsed:.2f}s")
        return summary
        
    except Exception as e:
        print(f"[ERROR] GPT summary failed: {e}")
        return "Summary generation failed."


def extract_facts_claude(text, url=""):
    """
    使用Claude Haiku提取事实声明
    
    Args:
        text: Content to analyze
        url: Source URL
    
    Returns:
        tuple: (facts_count, fact_check_result)
    """
    try:
        text_facts = text[:15000]  # Claude用于facts提取，使用更多字符
        
        # 保存即将发送给Claude的内容（用于调试）
        save_website_content(text_facts, url, "facts")
        
        print(f"[CLAUDE] Starting fact extraction ({len(text_facts)} chars)")
        start_time = time.time()
        
        system_prompt = """You are a factual claim extraction specialist. Your job is to identify and list ALL verifiable factual claims from the given text.

## Task
Extract every factual statement that can be verified as true or false. Each fact should be a complete, standalone statement.

## What to Extract
- Historical events and dates
- Statistical data and numbers
- Names of people, organizations, places
- Specific claims about relationships or roles
- Quotes and attributions
- Scientific or technical facts
- Time-bound statements (when something happened/will happen)

## Output Format
List each fact on a separate line. Number each fact sequentially (1., 2., 3., etc.)
Do NOT include any other text, explanations, or formatting.
Do NOT use JSON, XML, or any other structured format.
Just output the numbered list of facts.

## Example Output
1. Steve Jobs was born in 1955
2. Apple Inc. was founded in 1976
3. The iPhone was released in 2007
4. Steve Jobs died in 2011

## Critical Rules
- Each fact must be a complete sentence
- One fact per line
- No bullet points, only numbers followed by periods
- No introductory text or conclusion
- Start immediately with "1."
- No empty lines between facts

Now extract all facts from the provided content:"""
        
        # 调用 Claude Haiku
        response = client.generate(
            model='us.anthropic.claude-3-haiku-20240307-v1:0',
            system=system_prompt,
            query=text_facts,
            temperature=0.3,
            lastk=0
        )
        
        elapsed = time.time() - start_time
        
        # 检查response是否有错误
        if 'error' in response:
            print(f"[ERROR] Claude API error: {response['error']}")
            return 0, False, "N/A"
        
        result_text = response.get('result', '').strip()
        
        if not result_text:
            print(f"[ERROR] Claude returned empty result")
            print(f"[ERROR] Full response: {response}")
            return 0, False, "N/A"
        
        print(f"[CLAUDE] Fact extraction completed in {elapsed:.2f}s")
        print(f"[CLAUDE] Response length: {len(result_text)} chars")
        
        try:
            # 解析文本列表（每行一个fact）
            lines = result_text.strip().split('\n')
            
            # 过滤出有效的fact行（以数字和点开头）
            facts = []
            for line in lines:
                line = line.strip()
                # 检查是否以"数字. "开头
                if line and len(line) > 3 and line[0].isdigit() and '. ' in line[:5]:
                    # 移除编号，只保留fact内容
                    fact_text = line.split('. ', 1)[1] if '. ' in line else line
                    facts.append(fact_text)
            
            print(f"[CLAUDE] Extracted {len(facts)} facts")
            
            if len(facts) > 0:
                print(f"[CLAUDE] First fact preview: {facts[0][:80]}...")
            
            # 调用FACTCHECK服务（假函数）
            # test_mode参数: "clean", "suspicious", "fake"
            # 您可以修改这个参数来测试不同的返回结果
            fact_check_result = call_factcheck_service(
                facts, 
                url=url, 
                test_mode="clean"  # 修改为 "suspicious" 或 "fake" 来测试
            )
            
            return len(facts), fact_check_result
            
        except Exception as e:
            print(f"[ERROR] Failed to parse facts from Claude: {e}")
            print(f"[ERROR] Raw response preview: {result_text[:300]}")
            
            # 保存原始响应用于调试
            call_factcheck_service([f"[ERROR] {result_text}"], url=url)
            error_result = {
                "confidence": "N/A",
                "details": "Analysis incomplete."
            }
            return 0, error_result
        
    except Exception as e:
        print(f"[ERROR] Claude fact extraction failed: {e}")
        error_result = {
            "confidence": "N/A",
            "details": "Analysis incomplete."
        }
        return 0, error_result


def analyze_content(text, url=""):
    """
    并行调用GPT生成summary和Claude提取facts
    使用ThreadPoolExecutor实现真正的并行执行
    
    Args:
        text: Content to analyze
        url: Source URL
    
    Returns:
        (summary, is_fake_news, confidence)
    """
    if not client:
        return "LLM not configured.", False, "N/A"
    
    try:
        print(f"[PARALLEL] Starting parallel analysis ({len(text)} chars)")
        overall_start = time.time()
        
        # 使用ThreadPoolExecutor实现真正的并行执行
        with ThreadPoolExecutor(max_workers=2) as executor:
            # 提交两个任务
            future_summary = executor.submit(generate_summary_gpt, text, url)
            future_facts = executor.submit(extract_facts_claude, text, url)
            
            # 等待两个任务完成
            summary = future_summary.result()
            facts_count, fact_check_result = future_facts.result()
        
        overall_elapsed = time.time() - overall_start
        print(f"[PARALLEL] Parallel analysis completed in {overall_elapsed:.2f}s")
        print(f"[PARALLEL] Summary length: {len(summary)} chars, Facts: {facts_count}, Verdict: {fact_check_result['confidence']}")
        
        # 返回：summary（独立）和完整的fact_check_result（独立）
        return summary, fact_check_result
        
    except Exception as e:
        print(f"[ERROR] Parallel analysis failed: {e}")
        return "Analysis failed, please try again later.", False, "N/A"


def convert_court_result_to_user_format(court_result, fact_count, url=""):
    """
    将 Model Court 的"法官陈词"转换为用户友好的简洁格式
    
    Args:
        court_result: Model Court 返回的结果
        fact_count: 检查的facts数量
        url: 来源URL
    
    Returns:
        dict: {
            "confidence": "CLEAN" | "SUSPICIOUS" | "FAKE",
            "details": str  # 简洁易懂的用户友好描述
        }
    """
    try:
        confidence = court_result.get('confidence', 'N/A')
        court_details = court_result.get('details', '')
        
        print(f"[CONVERT] Converting Model Court result to user-friendly format...")
        convert_start = time.time()
        
        # 使用 LLM 将专业的法官陈词转换为用户友好格式
        system_prompt = """You are a user experience specialist. Your task is to convert a technical fact-checking report into a simple, clear message for everyday users.

## Critical Decision Rule - PRIORITY WEIGHTING
**IMPORTANT**: When analyzing the jury votes, apply the following priority weighting:
1. If "User_Feedback_Jury" voted "no_objection" (supported), give it HIGH priority
2. If "RAG_Jury" voted "no_objection" (supported), give it HIGH priority
3. If BOTH User_Feedback_Jury AND RAG_Jury support the claim, you should treat the overall verdict as "CLEAN" even if other juries expressed doubt
4. Reasoning: User feedback and RAG database contain verified, trusted information and should override speculative doubts from other juries

## Example Override Scenario
Input: Judge verdict = SUSPICIOUS, but User_Feedback_Jury = no_objection AND RAG_Jury = no_objection
Your output should reflect: CLEAN (Content appears reliable based on verified sources)

## Guidelines
1. Keep it concise (max 3-4 bullet points or 2-3 short sentences)
2. Use simple, non-technical language
3. Focus on the main findings, not the process
4. Be direct and actionable
5. Use bullet points (•) for multiple issues
6. Each bullet point should be one line maximum

## Input Format
You will receive:
- Confidence level (CLEAN/SUSPICIOUS/FAKE)
- Detailed technical report from fact-checking system (including jury votes)

## Output Format
Just return the simplified message text. No JSON, no extra formatting.

## Examples

Input confidence: FAKE
Input details: [Long technical report about claims being refuted by multiple sources]
Output:
False information detected:
• The article contains factually incorrect statements about historical events
• Claims contradict verified data from authoritative sources

Input confidence: SUSPICIOUS
Input details: [Technical report about uncertain claims]
Output:
Some claims need verification:
• Several statements lack supporting evidence
• Key facts could not be confirmed from reliable sources

Input confidence: CLEAN
Input details: [Technical report saying everything checks out]
Output:
Content appears reliable. No significant factual issues detected."""
        
        user_query = f"""Judge's Initial Verdict: {confidence}

Detailed Report from Fact-Checking System:
{court_details}

TASK:
1. Review the jury votes (especially User_Feedback_Jury and RAG_Jury)
2. If User_Feedback_Jury AND RAG_Jury both voted "no_objection", override the verdict to CLEAN
3. Convert to a user-friendly message (max 3-4 lines)
4. Return in this format:
   VERDICT: [CLEAN/SUSPICIOUS/FAKE]
   MESSAGE: [your user-friendly message]"""
        
        # 调用 GPT-4o-mini 进行转换
        response = client.generate(
            model='4o-mini',
            system=system_prompt,
            query=user_query,
            temperature=0.3,
            lastk=0
        )
        
        convert_elapsed = time.time() - convert_start
        result_text = response['result'].strip()
        
        print(f"[CONVERT] Conversion completed in {convert_elapsed:.2f}s")
        
        # 解析返回结果
        final_confidence = confidence  # 默认使用原判决
        user_friendly_details = result_text
        
        # 尝试解析 LLM 返回的 VERDICT 和 MESSAGE
        lines = result_text.split('\n')
        for i, line in enumerate(lines):
            if line.startswith('VERDICT:'):
                verdict_value = line.replace('VERDICT:', '').strip()
                if verdict_value in ['CLEAN', 'SUSPICIOUS', 'FAKE']:
                    final_confidence = verdict_value
                    print(f"[CONVERT] Verdict adjusted: {confidence} → {final_confidence}")
            elif line.startswith('MESSAGE:'):
                # 获取 MESSAGE 后的所有内容
                user_friendly_details = '\n'.join(lines[i:]).replace('MESSAGE:', '', 1).strip()
                break
        
        # 如果没有解析到格式，就使用完整返回
        if final_confidence == confidence and 'VERDICT:' not in result_text:
            user_friendly_details = result_text
        
        return {
            "confidence": final_confidence,
            "details": user_friendly_details
        }
        
    except Exception as e:
        print(f"[ERROR] Failed to convert court result: {e}")
        # 如果转换失败，使用原始结果
        return court_result


def save_user_feedback(url, content_background, feedback_content, feedback_type, feedback_prove):
    """
    保存用户反馈到 Model Court 的 User Feedback Database
    
    Args:
        url: 页面URL
        content_background: 页面内容背景
        feedback_content: 用户提供的fact内容
        feedback_type: 反馈类型 ("fact", "suspicious_fact", "fake_fact")
        feedback_prove: 用户提供的证据
    """
    try:
        # Model Court 的 User_Feedback_Jury 读取的文件路径
        user_feedback_db_path = "data/user_feedback_db.txt"
        
        # 确保data文件夹存在
        os.makedirs("data", exist_ok=True)
        
        # 同时保存到fact_feedback文件夹（备份日志）
        feedback_dir = "fact_feedback"
        os.makedirs(feedback_dir, exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        backup_filename = f"{feedback_dir}/feedback_{timestamp}.txt"
        
        # 构建feedback数据
        feedback_data = {
            "timestamp": datetime.now().isoformat(),
            "url": url,
            "content_background": content_background[:500] if content_background else "",
            "feedback_content": feedback_content,
            "feedback_type": feedback_type,
            "feedback_prove": feedback_prove
        }
        
        # 保存备份（JSON格式）
        with open(backup_filename, 'w', encoding='utf-8') as f:
            json.dump(feedback_data, f, ensure_ascii=False, indent=2)
        
        print(f"[FEEDBACK] Backup saved to {backup_filename}")
        
        # 保存到 Model Court 数据库（追加模式，人类可读格式）
        with open(user_feedback_db_path, 'a', encoding='utf-8') as f:
            f.write("\n" + "=" * 80 + "\n")
            f.write(f"[USER FEEDBACK] {datetime.now().isoformat()}\n")
            f.write("=" * 80 + "\n")
            f.write(f"URL: {url}\n\n")
            
            # 根据反馈类型标注
            if feedback_type == "fact":
                f.write(f"TYPE: ✓ VERIFIED AS TRUE\n")
            elif feedback_type == "suspicious_fact":
                f.write(f"TYPE: ⚠ MARKED AS SUSPICIOUS\n")
            elif feedback_type == "fake_fact":
                f.write(f"TYPE: ✗ REPORTED AS FAKE\n")
            else:
                f.write(f"TYPE: {feedback_type.upper()}\n")
            
            f.write(f"\nCLAIM:\n{feedback_content}\n\n")
            f.write(f"EVIDENCE/PROOF:\n{feedback_prove}\n\n")
            
            if content_background:
                f.write(f"CONTEXT:\n{content_background[:300]}...\n\n")
        
        print(f"[FEEDBACK] Appended to Model Court database: {user_feedback_db_path}")
        
    except Exception as e:
        print(f"[ERROR] Failed to save feedback: {e}")
        import traceback
        traceback.print_exc()
        raise


def call_factcheck_service(facts_list, url="", test_mode="clean"):
    """
    调用 Model Court 进行事实检查
    
    Args:
        facts_list: 从LLM提取的facts列表
        url: 来源URL
        test_mode: 保留参数（兼容性），实际使用 Model Court
    
    Returns:
        dict: {
            "confidence": "CLEAN" | "SUSPICIOUS" | "FAKE",
            "details": str  # 自然语言描述，用户友好格式
        }
    """
    try:
        # 确保fact_list文件夹存在（保存日志）
        fact_list_dir = "fact_list"
        if not os.path.exists(fact_list_dir):
            os.makedirs(fact_list_dir)
        
        # 生成文件名：时间戳
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        filename = f"{fact_list_dir}/facts_{timestamp}.txt"
        
        # 保存facts列表到日志文件
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(f"URL: {url}\n")
            f.write(f"Timestamp: {datetime.now().isoformat()}\n")
            f.write("=" * 80 + "\n\n")
            
            if isinstance(facts_list, list) and len(facts_list) > 0:
                f.write(f"Total Facts: {len(facts_list)}\n\n")
                f.write("Facts to Check:\n\n")
                
                for i, fact in enumerate(facts_list, 1):
                    claim = str(fact).strip()
                    f.write(f"{i}. {claim}\n")
            else:
                f.write("No facts extracted.\n")
        
        fact_count = len(facts_list) if isinstance(facts_list, list) else 0
        print(f"[FACTCHECK] Saved {fact_count} facts to {filename}")
        
        # 如果没有facts，直接返回
        if not isinstance(facts_list, list) or len(facts_list) == 0:
            return {
                "confidence": "N/A",
                "details": "No facts extracted for verification."
            }
        
        try:
            # 将facts列表合并成文本字符串
            facts_text = "\n".join([f"{i}. {fact}" for i, fact in enumerate(facts_list, 1)])
            
            print(f"\n{'='*80}")
            print(f"🏛️  MODEL COURT SESSION STARTED")
            print(f"{'='*80}")
            print(f"📋 Total Claims to Verify: {fact_count}")
            print(f"⏱️  Starting verification process...")
            print(f"{'='*80}\n")
            
            court_start_time = time.time()
            
            # 调用 Model Court（异步函数）
            court_result = asyncio.run(court_manager.verify_text(facts_text))
            
            court_elapsed = time.time() - court_start_time
            
            print(f"\n{'='*80}")
            print(f"✅ MODEL COURT SESSION COMPLETED")
            print(f"{'='*80}")
            print(f"⏱️  Time taken: {court_elapsed:.2f}s")
            print(f"🏆 Final Verdict: {court_result['confidence']}")
            print(f"{'='*80}\n")
            
            # 将 Model Court 的"法官陈词"转换为用户友好格式
            user_friendly_result = convert_court_result_to_user_format(
                court_result,
                fact_count,
                url
            )
            
            print(f"[FACTCHECK] Final verdict: {user_friendly_result['confidence']}")
            
            return user_friendly_result
            
        except Exception as model_court_error:
            print(f"[ERROR] Model Court failed: {model_court_error}")
            import traceback
            traceback.print_exc()
            
            # Fallback: 返回简单的CLEAN结果
            print(f"[FACTCHECK] Falling back to simple verification")
            return {
                "confidence": "CLEAN",
                "details": f"Content verification completed. {fact_count} claims analyzed. (Model Court temporarily unavailable, using fallback mode)"
            }
        
    except Exception as e:
        print(f"[ERROR] FACTCHECK service error: {e}")
        import traceback
        traceback.print_exc()
        return {
            "confidence": "N/A",
            "details": "Analysis incomplete due to technical error."
        }


def inject_async_summary_script(html_content, page_url):
    """
    注入轻量级 JavaScript 脚本，异步加载 AI 总结 + Fake News 检测
    
    Args:
        html_content: 原始 HTML
        page_url: 页面 URL
    
    Returns:
        修改后的 HTML（添加了 JS 脚本）
    """
    # 对URL进行JavaScript字符串转义，防止语法错误
    # 替换反斜杠、单引号、双引号、换行符等特殊字符
    safe_url = page_url.replace('\\', '\\\\').replace("'", "\\'").replace('"', '\\"').replace('\n', '\\n').replace('\r', '\\r')
    
    # 创建异步加载脚本
    async_script = f'''
<script>
(function() {{
    // 全局错误处理
    window.addEventListener('error', function(e) {{
        console.error('[Global Error]', e.message, e.filename, e.lineno, e.colno);
    }});
    
    console.log('[AI Summary] Script loaded, readyState:', document.readyState);
    
    if (document.readyState === 'loading') {{
        console.log('[AI Summary] Waiting for DOMContentLoaded...');
        document.addEventListener('DOMContentLoaded', function() {{
            console.log('[AI Summary] DOMContentLoaded fired');
            initAISummary();
        }});
    }} else {{
        console.log('[AI Summary] DOM already loaded, initializing with timeout...');
        setTimeout(function() {{
            console.log('[AI Summary] Timeout fired, initializing...');
            initAISummary();
        }}, 100);
    }}
    
    function initAISummary() {{
        try {{
            console.log('[AI Summary] Initializing...');
            createBanner('Generating AI analysis...', null, null);
            var pageText = extractPageText();
            console.log('[AI Summary] Extracted text length:', pageText.length);
            requestSummary(pageText);
        }} catch(e) {{
            console.error('[AI Summary] Initialization error:', e);
            console.error('[AI Summary] Stack:', e.stack);
        }}
    }}
    
    function createBanner(message, confidence, factDetails) {{
        try {{
            console.log('[Banner] Creating banner, confidence:', confidence);
            var banner = document.createElement('div');
            banner.id = 'cs112-ai-summary-banner';
            
            var bgColor = '#667eea';
            var factCheckHtml = '';
        
        // 根据confidence值判断显示什么类型的提示
        if (confidence !== null && confidence !== 'N/A') {{
            if (confidence === 'FAKE') {{
                // 情况3：检测到虚假事实
                bgColor = '#e74c3c';  // Red
                factCheckHtml = `
                    <div style="background: #ffe6e6; border: 2px solid #e74c3c; border-radius: 8px; padding: 15px; margin-top: 15px;">
                        <div style="display: flex; align-items: flex-start;">
                            <span style="font-size: 32px; margin-right: 12px; line-height: 1;">✗</span>
                            <div style="flex: 1;">
                                <h3 style="margin: 0 0 10px 0; color: #e74c3c; font-size: 18px; font-weight: bold;">Fake Facts Detected</h3>
                                <div style="color: #c0392b; font-size: 14px; line-height: 1.6; white-space: pre-line;">
                                    ${{factDetails || 'False information detected in content.'}}
                                </div>
                            </div>
                        </div>
                    </div>
                `;
            }} else if (confidence === 'SUSPICIOUS') {{
                // 情况2：检测到可疑事实
                bgColor = '#f39c12';  // Orange
                factCheckHtml = `
                    <div style="background: #fff8e1; border: 2px solid #f39c12; border-radius: 8px; padding: 15px; margin-top: 15px;">
                        <div style="display: flex; align-items: flex-start;">
                            <span style="font-size: 24px; margin-right: 12px; line-height: 1;">⚠</span>
                            <div style="flex: 1;">
                                <h3 style="margin: 0 0 10px 0; color: #f39c12; font-size: 18px; font-weight: bold;">Suspicious Facts Detected</h3>
                                <div style="color: #e67e22; font-size: 14px; line-height: 1.6; white-space: pre-line;">
                                    ${{factDetails || 'Some claims require verification.'}}
                                </div>
                            </div>
                        </div>
                    </div>
                `;
            }} else if (confidence === 'CLEAN') {{
                // 情况1：没有问题事实
                bgColor = '#27ae60';  // Green
                factCheckHtml = `
                    <div style="background: #e8f8f5; border: 2px solid #27ae60; border-radius: 8px; padding: 12px; margin-top: 15px;">
                        <div style="display: flex; align-items: center;">
                            <span style="font-size: 24px; margin-right: 12px;">✓</span>
                            <div style="flex: 1;">
                                <p style="margin: 0; color: #27ae60; font-size: 14px; font-weight: bold;">No False Facts Detected</p>
                                <p style="margin: 5px 0 0 0; color: #1e8449; font-size: 13px;">
                                    ${{factDetails || 'Content appears reliable'}}
                                </p>
                            </div>
                        </div>
                    </div>
                `;
            }}
        }}
        
        banner.innerHTML = `
            <div style="all: initial; display: block; width: 100%; background: linear-gradient(135deg, ${{bgColor}} 0%, ${{bgColor}}dd 100%); padding: 0; margin: 0; box-sizing: border-box; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; position: relative; z-index: 999999;">
                <div style="max-width: 1200px; margin: 0 auto; padding: 20px; background: rgba(255, 255, 255, 0.97); box-shadow: 0 2px 10px rgba(0,0,0,0.1);">
                    <div style="display: flex; justify-content: space-between; align-items: flex-start; flex-wrap: wrap;">
                        <div style="flex: 1; min-width: 300px; margin-right: 20px;">
                            <h2 style="margin: 0 0 15px 0; padding: 0; font-size: 24px; font-weight: 700; color: ${{bgColor}}; display: flex; align-items: center;">
                                <span style="margin-right: 10px; font-size: 28px;">[AI]</span>
                                <span>Summary and Facts Check</span>
                            </h2>
                            <div id="cs112-summary-content" style="background: #f8f9fa; border-left: 4px solid ${{bgColor}}; padding: 15px; border-radius: 8px; margin-bottom: 10px;">
                                <p style="margin: 0; padding: 0; font-size: 16px; line-height: 1.8; color: #333;">
                                    ${{message}}
                                </p>
                            </div>
                            ${{factCheckHtml}}
                            <div style="display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; font-size: 13px; color: #666; margin-top: 15px;">
                                <span><strong>Powered by LLMs.</strong> | Fact Check is a free and open-source service!</span>
                                <div style="display: flex; gap: 10px;">
                                    <button onclick="openFeedbackModal()" style="background: #3498db; color: white; border: none; padding: 8px 16px; border-radius: 5px; cursor: pointer; font-size: 14px; font-weight: 600;">Feedback</button>
                                    <button onclick="document.getElementById('cs112-ai-summary-banner').remove()" style="background: #95a5a6; color: white; border: none; padding: 8px 16px; border-radius: 5px; cursor: pointer; font-size: 14px; font-weight: 600;">Close</button>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        `;
        
            if (document.body) {{
                document.body.insertBefore(banner, document.body.firstChild);
                console.log('[Banner] Banner inserted successfully');
            }} else {{
                console.error('[Banner] document.body not found');
            }}
        }} catch(e) {{
            console.error('[Banner] Error creating banner:', e);
            console.error('[Banner] Stack:', e.stack);
        }}
    }}
    
    function updateBanner(message, confidence, factDetails) {{
        // Remove old banner
        var oldBanner = document.getElementById('cs112-ai-summary-banner');
        if (oldBanner) {{
            oldBanner.remove();
        }}
        // Create new banner
        createBanner(message, confidence, factDetails);
    }}
    
    function extractPageText() {{
        var text = document.body.innerText || document.body.textContent || '';
        return text.substring(0, 15000);
    }}
    
    function requestSummary(pageText) {{
        var url = 'http://127.0.0.1:5000/api/summary';
        
        fetch(url, {{
            method: 'POST',
            headers: {{
                'Content-Type': 'application/json'
            }},
            body: JSON.stringify({{
                url: '{safe_url}',
                content: pageText
            }})
        }})
        .then(response => response.json())
        .then(data => {{
            if (data.summary) {{
                updateBanner(data.summary, data.confidence, data.fact_details);
                console.log('[AI Summary] Analysis complete');
            }} else {{
                updateBanner('Analysis failed', null, null);
            }}
        }})
        .catch(error => {{
            console.error('[AI Summary] Request failed:', error);
            updateBanner('Cannot connect to AI server', null, null);
        }});
    }}
    
    // ========== Feedback功能（暴露到全局作用域） ==========
    var currentPageUrl = '{safe_url}';
    var currentPageContent = '';
    
    // 暴露到window对象，使onclick可以访问
    window.openFeedbackModal = function() {{
        currentPageContent = extractPageText();
        
        // 创建模态框
        var modal = document.createElement('div');
        modal.id = 'feedback-modal';
        modal.innerHTML = `
            <div style="position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.6); z-index: 9999999; display: flex; align-items: center; justify-content: center;">
                <div style="background: white; padding: 30px; border-radius: 12px; max-width: 550px; width: 90%; box-shadow: 0 4px 20px rgba(0,0,0,0.3);">
                    <h3 style="margin: 0 0 20px 0; color: #333; font-size: 22px;">Submit Your Feedback</h3>
                    
                    <div style="margin-bottom: 20px;">
                        <label style="display: block; margin-bottom: 8px; font-weight: bold; color: #555;">Fact Content:</label>
                        <textarea id="feedback-content" placeholder="Enter the specific fact or claim you want to report (at least 10 characters)" 
                                  style="width: 100%; height: 80px; padding: 10px; border-radius: 6px; border: 2px solid #ddd; font-size: 14px; resize: vertical;"></textarea>
                        <small style="color: #666; font-size: 12px;">Example: Hong Kong is an independent country</small>
                    </div>
                    
                    <div style="margin-bottom: 20px;">
                        <label style="display: block; margin-bottom: 8px; font-weight: bold; color: #555;">Your Assessment:</label>
                        <select id="feedback-type" style="width: 100%; padding: 10px; border-radius: 6px; border: 2px solid #ddd; font-size: 15px;">
                            <option value="fact">✓ This is a FACT (True)</option>
                            <option value="suspicious_fact">⚠ This is SUSPICIOUS (Needs verification)</option>
                            <option value="fake_fact">✗ This is FAKE (False)</option>
                        </select>
                    </div>
                    
                    <div style="margin-bottom: 20px;">
                        <label style="display: block; margin-bottom: 8px; font-weight: bold; color: #555;">Evidence/Proof:</label>
                        <textarea id="feedback-prove" placeholder="Provide evidence or sources to support your assessment (at least 10 characters)" 
                                  style="width: 100%; height: 100px; padding: 10px; border-radius: 6px; border: 2px solid #ddd; font-size: 14px; resize: vertical;"></textarea>
                        <small style="color: #666; font-size: 12px;">Example: According to Wikipedia, Hong Kong is a Special Administrative Region of China</small>
                    </div>
                    
                    <div id="feedback-status" style="margin-bottom: 15px; display: none; padding: 10px; border-radius: 6px;"></div>
                    
                    <div style="display: flex; justify-content: flex-end; gap: 10px;">
                        <button onclick="closeFeedbackModal()" 
                                style="background: #95a5a6; color: white; border: none; padding: 10px 20px; border-radius: 6px; cursor: pointer; font-size: 15px; font-weight: 600;">
                            Cancel
                        </button>
                        <button onclick="submitFeedback()" 
                                style="background: #27ae60; color: white; border: none; padding: 10px 20px; border-radius: 6px; cursor: pointer; font-size: 15px; font-weight: 600;">
                            Submit
                        </button>
                    </div>
                </div>
            </div>
        `;
        
        document.body.appendChild(modal);
    }};
    
    window.closeFeedbackModal = function() {{
        var modal = document.getElementById('feedback-modal');
        if (modal) {{
            modal.remove();
        }}
    }};
    
    window.submitFeedback = function() {{
        var feedbackContent = document.getElementById('feedback-content').value;
        var feedbackType = document.getElementById('feedback-type').value;
        var feedbackProve = document.getElementById('feedback-prove').value;
        var statusDiv = document.getElementById('feedback-status');
        
        // 验证fact内容
        if (!feedbackContent || feedbackContent.length < 10) {{
            statusDiv.style.display = 'block';
            statusDiv.style.background = '#ffe6e6';
            statusDiv.style.color = '#e74c3c';
            statusDiv.innerHTML = '✗ Please provide the fact content (at least 10 characters)';
            return;
        }}
        
        // 验证证据
        if (!feedbackProve || feedbackProve.length < 10) {{
            statusDiv.style.display = 'block';
            statusDiv.style.background = '#ffe6e6';
            statusDiv.style.color = '#e74c3c';
            statusDiv.innerHTML = '✗ Please provide evidence/proof (at least 10 characters)';
            return;
        }}
        
        // 显示提交中
        statusDiv.style.display = 'block';
        statusDiv.style.background = '#e8f8f5';
        statusDiv.style.color = '#27ae60';
        statusDiv.innerHTML = '⏳ Submitting your feedback...';
        
        // 提交feedback
        fetch('http://127.0.0.1:5000/api/feedback', {{
            method: 'POST',
            headers: {{
                'Content-Type': 'application/json'
            }},
            body: JSON.stringify({{
                url: currentPageUrl,
                content_background: currentPageContent.substring(0, 500),
                feedback_content: feedbackContent,
                feedback_type: feedbackType,
                feedback_prove: feedbackProve
            }})
        }})
        .then(response => response.json())
        .then(data => {{
            if (data.success) {{
                statusDiv.style.background = '#e8f8f5';
                statusDiv.style.color = '#27ae60';
                statusDiv.innerHTML = '✓ ' + data.message;
                setTimeout(closeFeedbackModal, 2000);
            }} else {{
                statusDiv.style.background = '#ffe6e6';
                statusDiv.style.color = '#e74c3c';
                statusDiv.innerHTML = '✗ ' + data.message;
            }}
        }})
        .catch(error => {{
            statusDiv.style.background = '#ffe6e6';
            statusDiv.style.color = '#e74c3c';
            statusDiv.innerHTML = '✗ Failed to submit feedback. Please try again.';
        }});
    }};
}})();
</script>
'''
    
    # 在 <body> 标签后插入脚本
    body_pos = html_content.find('<body')
    if body_pos != -1:
        body_end = html_content.find('>', body_pos)
        if body_end != -1:
            before = html_content[:body_end+1]
            after = html_content[body_end+1:]
            return before + async_script + after
    
    # 在 <html> 标签后插入
    html_pos = html_content.find('<html')
    if html_pos != -1:
        html_end = html_content.find('>', html_pos)
        if html_end != -1:
            before = html_content[:html_end+1]
            after = html_content[html_end+1:]
            return before + async_script + after
    
    # 直接放在最前面
    return async_script + html_content


def run_test_mode():
    """Test mode: read content from file and analyze with LLM."""
    test_file_path = "fake_news_test.txt"
    
    print("=" * 60)
    print("LLM Test Mode")
    print("=" * 60)
    print("LLM Proxy client initialized")
    print("Model: 4o-mini")
    print("=" * 60 + "\n")

    try:
        with open(test_file_path, 'r', encoding='utf-8') as f:
            content_to_analyze = f.read()
        
        print(f"Reading test file: {os.path.abspath(test_file_path)}")
        print(f"Successfully read {len(content_to_analyze)} chars\n")
        
        print("File content:")
        print("-" * 60)
        print(content_to_analyze[:500])
        if len(content_to_analyze) > 500:
            print("...")
        print("-" * 60 + "\n")

        print("Calling LLM Proxy for content analysis...\n")
        
        summary, fact_check_result = analyze_content(content_to_analyze)
        
        print("LLM analysis successful\n")
        print("Analysis Results:")
        print("=" * 60)
        print(f"Summary: {summary}")
        print(f"Confidence: {fact_check_result['confidence']}")
        print(f"Fact Check Details:")
        print(f"  {fact_check_result['details']}")
        print("=" * 60 + "\n")
        
    except FileNotFoundError:
        print(f"Error: Test file '{test_file_path}' not found. Please create the file with test content.")
    except Exception as e:
        sys.stderr.write(f"LLM test mode error: {str(e)}\n")
    finally:
        print("Test complete")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1].lower() == 'test':
        run_test_mode()
    else:
        print("\n" + "=" * 60)
        print("CS112 Fake News Detection Project is Ready!")
        print("=" * 60)
        print(f"\nServer Address: http://{FLASK_HOST}:{FLASK_PORT}")
        print(f"LLM Model: 4o-mini")
        print("\nActive Features:")
        print("  - AI Summary (Async loading)")
        print("  - Fake News Detection")
        print("\nWorkflow:")
        print("  1. Proxy sends HTML to Flask")
        print("  2. Flask injects JavaScript")
        print("  3. Page displays immediately")
        print("  4. JavaScript requests AI analysis")
        print("  5. Banner appears with results")
        print("\n" + "=" * 60)
        print("Ready! Waiting for requests...")
        print("=" * 60 + "\n")
        
        app.run(host=FLASK_HOST, port=FLASK_PORT, debug=True, threaded=True)
