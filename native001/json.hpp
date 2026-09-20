#pragma once
#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <iomanip>
#include <limits>
#include <map>
#include <sstream>
#include <stdexcept>
#include <string>
#include <variant>
#include <vector>

namespace rcwg {
struct Fault : std::runtime_error {
    std::string attribution;
    explicit Fault(const std::string& code, std::string blame="facility")
      :std::runtime_error(code),attribution(std::move(blame)){}
};
struct J {
    using A=std::vector<J>; using O=std::map<std::string,J>;
    std::variant<std::nullptr_t,bool,int64_t,double,std::string,A,O> v;
    J():v(nullptr){} J(std::nullptr_t):v(nullptr){} J(bool x):v(x){}
    J(int64_t x):v(x){} J(int x):v(int64_t(x)){} J(double x):v(x){}
    J(const char* x):v(std::string(x)){} J(std::string x):v(std::move(x)){}
    J(A x):v(std::move(x)){} J(O x):v(std::move(x)){}
    bool null()const{return v.index()==0;} bool boolean()const{return v.index()==1;}
    bool integer()const{return v.index()==2;} bool number()const{return integer()||v.index()==3;}
    bool string()const{return v.index()==4;} bool array()const{return v.index()==5;}
    bool object()const{return v.index()==6;}
    const A& arr()const{if(!array())throw Fault("JSON_ARRAY_REQUIRED");return std::get<A>(v);}
    const O& obj()const{if(!object())throw Fault("JSON_OBJECT_REQUIRED");return std::get<O>(v);}
    const std::string& str()const{if(!string())throw Fault("JSON_STRING_REQUIRED");return std::get<std::string>(v);}
    int64_t i()const{if(!integer())throw Fault("JSON_INT_REQUIRED");return std::get<int64_t>(v);}
    double d()const{if(!number())throw Fault("JSON_NUMBER_REQUIRED");return integer()?double(i()):std::get<double>(v);}
    bool b()const{if(!boolean())throw Fault("JSON_BOOL_REQUIRED");return std::get<bool>(v);}
    const J& at(const std::string& k)const{auto& o=obj();auto it=o.find(k);if(it==o.end())throw Fault("JSON_MISSING_FIELD");return it->second;}
    bool has(const std::string& k)const{return object()&&obj().count(k);}
};
inline size_t utf8_count(const std::string& s) {
    size_t n=0;
    for(size_t i=0;i<s.size();++n){
        unsigned c=(unsigned char)s[i++],cp=0;int extra=0;
        if(c<128)continue;
        if(c>=0xc2&&c<=0xdf){cp=c&31;extra=1;}
        else if(c>=0xe0&&c<=0xef){cp=c&15;extra=2;}
        else if(c>=0xf0&&c<=0xf4){cp=c&7;extra=3;}
        else throw Fault("DATA_UTF8_INVALID");
        int len=extra;
        while(extra--){if(i>=s.size()||((unsigned char)s[i]&0xc0)!=0x80)throw Fault("DATA_UTF8_INVALID");cp=(cp<<6)|((unsigned char)s[i++]&63);}
        if((len==1&&cp<128)||(len==2&&cp<0x800)||(len==3&&cp<0x10000)||cp>0x10ffff||(cp>=0xd800&&cp<=0xdfff))throw Fault("DATA_UTF8_INVALID");
    }
    return n;
}
inline void append_utf8(std::string& s,uint32_t c){
    if(c<128)s.push_back(char(c));
    else if(c<0x800){s.push_back(char(0xc0|(c>>6)));s.push_back(char(0x80|(c&63)));}
    else if(c<0x10000){s.push_back(char(0xe0|(c>>12)));s.push_back(char(0x80|((c>>6)&63)));s.push_back(char(0x80|(c&63)));}
    else{s.push_back(char(0xf0|(c>>18)));s.push_back(char(0x80|((c>>12)&63)));s.push_back(char(0x80|((c>>6)&63)));s.push_back(char(0x80|(c&63)));}
}
class Parser {
    const std::string& s;size_t p=0;
    char peek()const{return p<s.size()?s[p]:'\0';}
    void ws(){while(peek()==' '||peek()=='\n'||peek()=='\r'||peek()=='\t')++p;}
    void need(char c){if(peek()!=c)throw Fault("DATA_JSON_INVALID");++p;}
    uint32_t hex(){uint32_t n=0;for(int j=0;j<4;++j){char c=peek();++p;int x=(c>='0'&&c<='9')?c-'0':(c>='a'&&c<='f')?c-'a'+10:(c>='A'&&c<='F')?c-'A'+10:-1;if(x<0)throw Fault("DATA_JSON_INVALID");n=n*16+unsigned(x);}return n;}
    std::string text(){
        need('"');std::string r;
        while(peek()!='"'){
            unsigned char c=peek();if(c<32)throw Fault("DATA_JSON_INVALID");++p;
            if(c!='\\'){r.push_back(char(c));continue;}
            char e=peek();++p;
            switch(e){case '"':case '\\':case '/':r.push_back(e);break;case 'b':r+='\b';break;case 'f':r+='\f';break;case 'n':r+='\n';break;case 'r':r+='\r';break;case 't':r+='\t';break;
            case 'u':{uint32_t cp=hex();if(cp>=0xd800&&cp<=0xdbff){need('\\');need('u');uint32_t lo=hex();if(lo<0xdc00||lo>0xdfff)throw Fault("DATA_UTF8_INVALID");cp=0x10000+((cp-0xd800)<<10)+(lo-0xdc00);}else if(cp>=0xdc00&&cp<=0xdfff)throw Fault("DATA_UTF8_INVALID");append_utf8(r,cp);break;}
            default:throw Fault("DATA_JSON_INVALID");}
        }
        ++p;utf8_count(r);return r;
    }
    J value(unsigned depth){
        if(depth>128)throw Fault("DATA_JSON_DEPTH_CAP");ws();char c=peek();
        if(c=='"')return J(text());
        if(c=='{'){++p;ws();J::O o;if(peek()=='}'){++p;return o;}while(true){ws();auto k=text();ws();need(':');auto v=value(depth+1);if(!o.emplace(k,std::move(v)).second)throw Fault("DATA_DUPLICATE_KEY");ws();if(peek()=='}'){++p;return o;}need(',');}}
        if(c=='['){++p;ws();J::A a;if(peek()==']'){++p;return a;}while(true){a.push_back(value(depth+1));ws();if(peek()==']'){++p;return a;}need(',');}}
        for(auto token:{"true","false","null"}){std::string t=token;if(s.compare(p,t.size(),t)==0){p+=t.size();if(t=="true")return true;if(t=="false")return false;return nullptr;}}
        size_t start=p;if(peek()=='-')++p;
        if(peek()=='0')++p;else {if(peek()<'1'||peek()>'9')throw Fault("DATA_JSON_INVALID");while(peek()>='0'&&peek()<='9')++p;}
        bool real=false;
        if(peek()=='.'){real=true;++p;if(peek()<'0'||peek()>'9')throw Fault("DATA_JSON_INVALID");while(peek()>='0'&&peek()<='9')++p;}
        if(peek()=='e'||peek()=='E'){real=true;++p;if(peek()=='+'||peek()=='-')++p;if(peek()<'0'||peek()>'9')throw Fault("DATA_JSON_INVALID");while(peek()>='0'&&peek()<='9')++p;}
        auto token=s.substr(start,p-start);
        if(real){char* end=nullptr;double x=std::strtod(token.c_str(),&end);if(!std::isfinite(x)||end!=token.c_str()+token.size())throw Fault("DATA_NONFINITE");return x;}
        try{size_t end;auto x=std::stoll(token,&end);if(end!=token.size())throw Fault("DATA_JSON_INVALID");return int64_t(x);}catch(const std::out_of_range&){throw Fault("DATA_INT64_RANGE");}
    }
public:
    explicit Parser(const std::string& input):s(input){}
    J parse(){auto r=value(0);ws();if(p!=s.size())throw Fault("DATA_JSON_INVALID");return r;}
};
inline std::string quote(const std::string& s){
    std::ostringstream o;o<<'"';for(unsigned char c:s){switch(c){case '"':o<<"\\\"";break;case '\\':o<<"\\\\";break;case '\b':o<<"\\b";break;case '\f':o<<"\\f";break;case '\n':o<<"\\n";break;case '\r':o<<"\\r";break;case '\t':o<<"\\t";break;default:if(c<32)o<<"\\u"<<std::hex<<std::setw(4)<<std::setfill('0')<<int(c)<<std::dec;else o<<c;}}o<<'"';return o.str();
}
inline std::string dump(const J& j){
    if(j.null())return "null";if(j.boolean())return j.b()?"true":"false";if(j.integer())return std::to_string(j.i());
    if(j.number()){if(!std::isfinite(j.d()))throw Fault("OUTPUT_NONFINITE");std::ostringstream o;o<<std::setprecision(17)<<j.d();std::string s=o.str();if(s.find_first_of(".eE")==std::string::npos)s+=".0";return s;}
    if(j.string())return quote(j.str());std::string r;bool first=true;
    if(j.array()){r="[";for(auto& x:j.arr()){if(!first)r+=',';first=false;r+=dump(x);}return r+"]";}
    r="{";for(auto& kv:j.obj()){if(!first)r+=',';first=false;r+=quote(kv.first)+":"+dump(kv.second);}return r+"}";
}
}
