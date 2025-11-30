# Fact Check on News and Websites

**This project utilizes an HTTPS proxy and Model Court to build a mechanism for cross-validating webpage information, attempting to detect suspicious and false information.**

The HTTPS proxy can intercept all webpages, even those containing hidden information. This provides a technological foundation for future expansion of phishing website content and malicious content distribution.

Model Court is a cross-validation LLM-AS-JUDGE system designed to review content through a courtroom-like trial process. Model Court firstly is designed to make this project's fact check more reliable, but when we developing Model Court, we found its value is much higher than a partial module, so we have packaged Model Court into a Python package and will continue to be maintained as an open-source project. Details can be found on the [Model Court project page](https://github.com/LogicGate-AI-Lab/model-court) or [Model Court PYPI Introduction Page](https://pypi.org/project/model-court/).

Furthermore, this project includes a user feedback function, making the overall judgment more reliable. Because the system follows the presumption of innocence principle—using stricter standards to judge false information—the harm of fake news being judged as true outweighs the harm of true news being judged as false, just as the harm of an innocent person being convicted in a trial outweighs the harm of a guilty person being acquitted.

## Introduction

![Project Descriptions](docs/server_description.png)

The user interaction module is now in discussion and design stage.

The plan is to allow users to click "Fake" or "Real", and maintain a simple community of fact checks.

But the fact check should based on the content or the website? This is still in discussion and will update in later versions.

Core Modules:

- HTTPS Proxy: proxy.c
- Web

## Quick Start

Make sure you have already set up the LLM API keys and make c file.

Make sure you have already set up the browser or testing environment.

For HTTPS proxy server: (Recommended Settings)

```bash
# Use LLM server.
./proxy 8080 proxy_ca.crt proxy_ca.key llm=true

# Don't use LLM server and will only inject info on headers.
# This is for testing proxy program to see if it is running correctly.
./proxy 8080 proxy_ca.crt proxy_ca.key llm=false
```

For LLM server:

```bash
# Normal Mode（Port: 5000）
python3 fake_news.py

# Test Mode（Independent test，don't need proxy，auto load fake_news_test.txt）
python3 fake_news.py test
```

For Model Court:

You need install model court firstly. I have packaged model court as a python package, you can find:

* pip package: [https://pypi.org/project/model-court/](https://pypi.org/project/model-court/)
* repo: [https://github.com/LogicGate-AI-Lab/model-court](https://github.com/LogicGate-AI-Lab/model-court)

.

## Summary Function

The summary is for the whole page's content, it can help user know the main idea of the webpage and also be used in fact check modules, like feedback archive.

Technically, the web server sends a large number of TCP packets, so the proxy loops continuously until it receives the complete webpage content. It then reassembles the data, obtains the HTML file, extracts the plain text from the HTML, and sends it to the LLM (Linux Virtual Machine) for summarization.

To provide a better user experience, the summary function is performed separately and asynchronously. This means the HTTPS proxy directly returns the page content to the user, who can then browse the webpage. Meanwhile, the Summary section at the top of the page is in progress until the LLM returns the summary result.

![alt text](docs/1.png)

## Fact Check

Use Factcheck HTTPS proxy, you can find there is a framework on the top of the website, and give you feedbacks on the page's content.

![alt text](docs/1.png)

If there is suspecious content included, it will became orange:

![alt text](docs/2.png)

If there are more suspecious content included, it will became red, the judgement rules are based on model court, which will be introducted later.

![alt text](docs/3.png)

## Model Court

Model Court is a llm-as-judge model that use several llms to cross validation. This is comprehensive so we have built this part into a python package.

You can find more information through:

* pip package: [https://pypi.org/project/model-court/](https://pypi.org/project/model-court/)
* repo: [https://github.com/LogicGate-AI-Lab/model-court](https://github.com/LogicGate-AI-Lab/model-court)

In Fact Check, we set up five llms to judge the fact:

![alt text](docs/model_court.png)

The judgement is through following steps: (More details please see the package model-court)

1. The prosecutor will check if this content is already in the court code. If already exist and still valid, then this content will not be judged through model court.
2. If the content is not judged before, then this case will go into the court. Five juries will independtly give their decisions. The jury will give:

- no_objection: there is no fact looks like false
- suspicious_fact: there is some suspeicous fact but has no solid prove
- reasonable_doubt: high possibly false
- obstain: the jury face network or any other problem, or cannot judge so give up

3. The judge will conduct all juries' decisions and finish the case. The verdict only output when there are at least three juries' decisions. The verdict rule is:

- CLEAN: No objection
- SUSPICIOUS: 1-2 objections
- REFUTED: 3 or more objections

4. The Fact Check will give feedback based on the court:

CLEAN:

- The judge's verdict is CLEAN.
- Verdict contain only 1 objection, and rag/text is no_objection.

SUSPICIOUS:

- The judge's verdict is SUSPICIOUS.

FAKE:

- The judge's verdict is REFUTED.

## Human Feedback

If there is misled fact check result, the one who knows the truth can give feedbacks:

![alt text](docs/feedback1.png)

For example, this news is true but the Fact Check think it is false:

![alt text](docs/3.png)

The system employs a relatively strict trial mechanism because judging a genuine error as having a false impact is less important than judging a false error as having a genuine impact. This is also a characteristic of the legal principle of "presumption of innocence."

But if one is very confident on the result, he can input his prove:

![alt text](docs/feedback2.png)

Then click submit. This result will be recorded. Staff can review this feedback. Let's assume the feedback is genuine and valid.

Now, let's refresh the page again.

![alt text](docs/feedback4.png)

This webpage became CLEAN. We gave higher weight to The Archivist Jury (querying RAG) and The Community Watch Jury (querying user feedback). For example, if a jury gives a decision that is not no_objection, but The Archivist Jury and The Community Watch Jury find no problems after reviewing it, we will adjust the final result to CLEAN.
