import ast
import argparse
import sys
import re
import bisect
import traceback
import operator
import functools
import unicodedata

import tokenize
import pegen.parser
import lolcode_parser

class make_true:
    def __init__(self, s, coord, filename):
        self.s=s
        self.coord=coord
        self.filename = filename
    def __pos__(self):
        return self.s
    def __radd__(self, oth):
        return oth+ +self
    def __repr__(self):
        return f'{self.s!r} at {self.filename}:{self.coord[0]}:{self.coord[1]}'


class char_tokenizer:
    def __init__(self, text, filename):
        self.text = text
        self.filename = filename
        self.pos = 0
        self.max_pos = 0
        self.line_starts_list=[0]
        self.line_starts_set={0}
    def mark(self):
        return self.pos
    def reset(self, mark):
        self.pos = mark
        if self.pos > self.max_pos:
            self.max_pos = self.pos
    def get_coordinates(self):
        line_num = bisect.bisect_right(self.line_starts_list, self.pos)-1
        pos_in_line = self.pos - self.line_starts_list[line_num]
        return line_num+1, pos_in_line
    def peek(self):
        buffer = self.text[self.pos:self.pos+64]
        line_num, pos_in_line = self.get_coordinates()
        return tokenize.TokenInfo(54, buffer, (line_num, pos_in_line), (line_num, pos_in_line+64), repr(buffer))
    def diagnose(self):
        return self.peek()
    def expect(self, reg: str):
        buffer = self.text[self.pos:self.pos+64]
        match = re.match(reg, buffer, re.S)
        if match is None:
            return None
        length = match.regs[0][1]
        res = self.text[self.pos:self.pos+length]
        for q,w in enumerate(res):
            if w=='\n':
                if self.pos + q not in self.line_starts_set:
                    self.line_starts_list.append(self.pos + q)
                    self.line_starts_set.add(self.pos + q)
                    assert self.line_starts_list == sorted(self.line_starts_list)
        coord = self.get_coordinates()
        self.pos += length
        return make_true(res, coord, self.filename)


class char_parser(lolcode_parser.GeneratedParser):
    @pegen.parser.memoize
    def expect(self, type: str):
        return self._tokenizer.expect(type)
    def unicode_lookup(self, query):
        try:
            return unicodedata.lookup(query)
        except KeyError:
            return None

def simple_parser_main(parser_class) -> None:
    argparser = argparse.ArgumentParser()
    argparser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="Debug the parser",
    )
    argparser.add_argument(
        "-a",
        "--ast",
        action="count",
        default=0,
        help="print ast instead of running",
    )
    argparser.add_argument("filename", help="Input file ('-' to use stdin)")

    args = argparser.parse_args()
    verbose_parser = args.verbose

    with open(args.filename) as file:
        tokenizer=char_tokenizer(file.read(), args.filename)
        parser = parser_class(tokenizer, verbose=verbose_parser)
        tree = parser.start()

    if not tree:
        tokenizer.reset(tokenizer.max_pos)
        coord = tokenizer.get_coordinates()
        print(f'ERROR: SyntaxError at {tokenizer.filename}:{coord[0]}:{coord[1]}', file=sys.stderr)
        sys.exit(1)

    if args.ast:
        print(ast.dump(tree, indent=4))
    else:
        res = lol_exec(tree.body, {'IT': None})
        match res:
            case ast.Return() | ast.Break():
                print(f'ERROR: Calling {res.token} in global scope is not allowed.', file=sys.stderr)
                exit(1)

type_names = {
    type(None): 'NOOB',
    bool: 'TROOF',
    int: 'NUMBR',
    float: 'NUMBAR',
    str: 'YARN',
    type: 'TYPE',
}

def lol_str(value):
    if value is None:
        return 'NOOB'
    if isinstance(value, bool):
        return 'FAIL WIN'.split()[value]
    if isinstance(value, type):
        return type_names[value]
    if isinstance(value, float):
        return f'{value:.2f}'
    return str(value)

def lol_bool(value):
    return bool(value)

def lol_num(value, type):
    try:
        return type(value)
    except ValueError:
        print(f'ERROR: Cannot convert {value!r} to {type_names[type]}.', file=sys.stderr)
        exit(1)

functions = {}

def make_name_error(token):
    print(f'ERROR: Variable with name {token.token} is not declared. (Use I HAS A <name> to declare.)', file=sys.stderr)
    exit(1)

def make_func_error(token):
    print(f'ERROR: Function with name {token.token} is not declared. (Use HOW IZ I <name> to declare.)', file=sys.stderr)
    exit(1)

def lol_eval(tree, frame):
    match tree:
        case ast.BinOp(left, op, right):
            old_left = left
            old_right = right
            left = lol_eval(left, frame)
            right = lol_eval(right, frame)
            match op:
                case ast.Add() | ast.Mult() | ast.Div() | ast.Mod() | ast.Sub() | ast.Gt() | ast.Lt():
                    if isinstance(left, float) \
                    or isinstance(left, str) and '.' in left \
                    or isinstance(right, float) \
                    or isinstance(right, str) and '.' in right:
                        left = lol_num(left, float)
                        right = lol_num(right, float)
                    else:
                        left = lol_num(left, int)
                        right = lol_num(right, int)
                    match op:
                        case ast.Add(): return left + right
                        case ast.Sub(): return left - right
                        case ast.Mult(): return left * right
                        case ast.Div(): return left // right
                        case ast.Mod(): return left % right
                        case ast.Gt(): return max(left, right)
                        case ast.Lt(): return min(left, right)
                case ast.BitAnd() | ast.BitXor() | ast.BitOr():
                    left = lol_bool(left)
                    right = lol_bool(left)
                    match op:
                        case ast.BitAnd(): return left and right
                        case ast.BitOr(): return left or right
                        case ast.BitXor(): return left and not right or right or not left
                case ast.Eq():
                    return left == right
                case ast.NotEq():
                    return left != right
                case ast.LShift() | ast.RShift():
                    if right in [int, float]:
                        res = lol_num(left, right)
                    if right == str:
                        res = lol_str(left)
                    if right == type(None):
                        res = None
                    if right == type:
                        if type(left) != type:
                            print(f'ERROR: Cannot cast {type_names[type(left)]} to TYPE', file=sys.stderr)
                    if right == bool:
                        res = lol_bool(left)
                    match op:
                        case ast.LShift():
                            frame[old_left.id] = res
                    return res
        case ast.UnaryOp(op, operand):
            match op:
                case ast.Not(): return not lol_bool(lol_eval(operand, frame))
                case ast.UAdd(): offset=1
                case ast.USub(): offset=-1
            oper = lol_eval(operand, frame)
            if isinstance(oper, float) \
            or isinstance(oper, str) and '.' in oper:
                oper = lol_num(oper, float)
            else:
                oper = lol_num(oper, int)
            frame[operand.id] = offset + oper
            return frame[operand.id]
        case ast.Compare(left, ops, comparators):
            match ops[0]:
                case ast.JoinedStr(): return ''.join([lol_str(lol_eval(q, frame)) for q in comparators])
                case ast.And(): new_op, start = ast.BitAnd(), ast.Constant(True)
                case ast.Or(): new_op, start = ast.BitOr(), ast.Constant(False)
            reducer = lambda l,r: ast.BinOp(left=l, op=new_op, right=r)
            return lol_eval(functools.reduce(reducer, comparators, start), frame)
        case ast.Constant(value):
            return value
        case ast.Name(name):
            if name not in frame:
                make_name_error(tree)
            return frame[name]
        case ast.Call(func=func, args=args):
            if func.id not in functions:
                make_func_error(func)
            f = functions[func.id]
            if len(f.args.args) < len(args):
                print(f'ERROR: Too much args to a function call {func.token}.', file=sys.stderr)
                exit(1)
            if len(f.args.args) > len(args):
                print(f'ERROR: Too few args to a function call {func.token}.', file=sys.stderr)
                exit(1)
            new_frame = {'IT': None} | {
                q.arg:lol_eval(w, frame)
                for q,w in zip(f.args.args, args)
            }
            res = lol_exec(f.body, new_frame)
            match res:
                case ast.Pass():
                    return new_frame['IT']
                case ast.Break():
                    return
                case ast.Return(value):
                    return value
        case a:
            print('lol_eval', a)

def lol_exec(tree_list, frame):
    for line in tree_list:
        match line:
            case ast.Expr(value):
                value = lol_eval(value, frame)
            case ast.Assign(targets, value):
                value = lol_eval(value, frame)
                for target in targets:
                    if target.id not in frame:
                        make_name_error(target)
                    frame[target.id] = value
                # print(f'assign {value!r} to {target.id}')
            case ast.AnnAssign(target=target, value=value):
                value = lol_eval(value, frame)
                frame[target.id] = value
                # print(f'assign {value!r} to {target.id}')
            case ast.FunctionDef(name=name, args=args, body=body):
                functions[name] = line
            case ast.Return(value=value):
                line.value = lol_eval(value, frame)
                return line
            case ast.Break():
                return line
            case ast.If(test, body, orelse):
                if lol_bool(lol_eval(test, frame)):
                    res = lol_exec(body, frame)
                else:
                    res = lol_exec(orelse, frame)
                match res:
                    case ast.Return() | ast.Break():
                        return res
            case ast.Match(subject, cases):
                ev_subject = lol_eval(subject, frame)
                entered = False
                for case in cases:
                    if entered or isinstance(case.pattern, ast.MatchAs) or ev_subject == lol_eval(case.pattern, frame):
                        entered = 1
                        res = lol_exec(case.body, frame)
                        match res:
                            case ast.Return():
                                return res
                            case ast.Break():
                                break
            case ast.While(test, body):
                while lol_bool(lol_eval(test, frame)):
                    res = lol_exec(body, frame)
                    match res:
                        case ast.Return():
                            return res
                        case ast.Break():
                            break
            case ast.Load(value=value):
                if value.id not in frame:
                    make_name_error(value)
                frame[value.id] = input()
            case ast.Store(values=values, end=end):
                values = [lol_str(lol_eval(q, frame)) for q in values]
                print(*values, sep='', end=end)
            case a:
                print('lol_exec', a)
    return ast.Pass()


if __name__ == '__main__':
    simple_parser_main(char_parser)
